from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.providers.adapters import ProviderDependencyUnavailable, create_chat_model, create_provider
from app.providers.protocol import (
    Cancelled,
    Finished,
    ProviderRequest,
    RetryableError,
    StructuredOutput,
    TerminalError,
    TextDelta,
    ToolCall,
    Usage,
)
from app.providers.scripted import (
    Disconnect,
    MalformedAction,
    ScriptedProvider,
    SlowStream,
    deterministic_usage,
    tool_request,
)
from app.workers.task_pool import TaskWorkerPool
from app.workers.context import ContextSelectionMetadata


def request(request_id: str = "request-1") -> ProviderRequest:
    return ProviderRequest(
        request_id=request_id,
        model_id="fake-model",
        messages=({"role": "user", "content": "Implement the task."},),
    )


@pytest.mark.asyncio
async def test_scripted_provider_normalizes_stream_tool_usage_and_finish() -> None:
    provider = ScriptedProvider((
        (
            TextDelta("Hello"),
            SlowStream(0),
            tool_request("tool-1", "search_files", {"query": "TODO"}),
            deterministic_usage(11, 7, cost_usd=0.002),
            Finished(),
        ),
    ))

    events = [event async for event in provider.stream(request())]

    assert isinstance(events[0], TextDelta)
    assert events[0].text == "Hello"
    assert events[1].name == "search_files"
    assert events[2].total_tokens == 18
    assert events[2].cost_usd == 0.002
    assert isinstance(events[3], Finished)


@pytest.mark.asyncio
async def test_scripted_provider_covers_disconnect_malformed_output_and_cancellation() -> None:
    provider = ScriptedProvider((
        (MalformedAction({"unexpected": "action"}), Disconnect(retry_after_ms=250)),
        (SlowStream(0.05), TextDelta("must not arrive")),
    ))

    first = [event async for event in provider.stream(request("first"))]
    assert isinstance(first[0], StructuredOutput)
    assert first[0].value == {"unexpected": "action"}
    assert isinstance(first[1], RetryableError)
    assert first[1].code == "provider_disconnected"
    assert first[1].retry_after_ms == 250

    await provider.cancel("second")
    second = [event async for event in provider.stream(request("second"))]
    assert second == [Cancelled()]


def test_configuring_one_provider_loads_only_its_adapter_module() -> None:
    loaded: list[str] = []

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    def loader(name: str) -> object:
        loaded.append(name)
        return SimpleNamespace(ChatOpenAI=FakeOpenAI)

    model = create_chat_model(
        "openai_compat", model_id="test", api_key="runtime-only", module_loader=loader
    )

    assert isinstance(model, FakeOpenAI)
    assert loaded == ["langchain_openai"]


@pytest.mark.parametrize(
    ("kind", "module_name", "constructor"),
    [
        ("anthropic", "langchain_anthropic", "ChatAnthropic"),
        ("google", "langchain_google_genai", "ChatGoogleGenerativeAI"),
    ],
)
def test_each_provider_loads_only_its_own_optional_sdk(kind: str, module_name: str, constructor: str) -> None:
    loaded: list[str] = []

    class FakeModel:
        def __init__(self, **_: object) -> None:
            pass

    def loader(name: str) -> object:
        loaded.append(name)
        return SimpleNamespace(**{constructor: FakeModel})

    create_chat_model(kind, model_id="test", api_key="runtime-only", module_loader=loader)
    assert loaded == [module_name]


def test_missing_optional_provider_dependency_has_safe_actionable_error() -> None:
    def missing(_: str) -> object:
        raise ModuleNotFoundError("missing")

    with pytest.raises(ProviderDependencyUnavailable, match="provider dependency group"):
        create_chat_model("google", model_id="test", api_key="runtime-only", module_loader=missing)


@pytest.mark.asyncio
async def test_production_adapter_normalizes_a_lazy_chat_model_stream() -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.tools: list[object] | None = None
            self.response_schema: dict[str, object] | None = None

        def bind_tools(self, tools: list[object]) -> "FakeModel":
            self.tools = tools
            return self

        def with_structured_output(self, schema: dict[str, object], *, include_raw: bool) -> "FakeModel":
            assert include_raw is True
            self.response_schema = schema
            return self

        async def astream(self, _: list[object]):
            yield SimpleNamespace(
                content="Hello",
                tool_calls=[{"id": "call-1", "name": "read_file", "args": {"path": "README.md"}}],
                additional_kwargs={"parsed": {"action": "wait"}},
                usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                response_metadata={"finish_reason": "stop"},
            )

    fake_model = FakeModel()
    provider = create_provider(
        "openai", model_id="test", api_key="runtime-only", module_loader=lambda _: SimpleNamespace(ChatOpenAI=lambda **_: fake_model)
    )
    configured_request = ProviderRequest(
        request_id="request-1",
        model_id="fake-model",
        messages=({"role": "user", "content": "Implement the task."},),
        tools=({"name": "read_file", "description": "Read a file"},),
        response_schema={"type": "object", "properties": {"action": {"type": "string"}}},
    )
    events = [event async for event in provider.stream(configured_request)]

    assert events == [
        TextDelta("Hello"),
        ToolCall("call-1", "read_file", {"path": "README.md"}),
        StructuredOutput({"action": "wait"}),
        Usage(input_tokens=3, output_tokens=2, total_tokens=5),
        Finished(),
    ]
    assert fake_model.tools == [{"name": "read_file", "description": "Read a file"}]
    assert fake_model.response_schema == {"type": "object", "properties": {"action": {"type": "string"}}}


def test_minimal_sidecar_import_avoids_optional_provider_and_langgraph_modules() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.main, sys; print(','.join(sorted(name for name in sys.modules "
            "if name.startswith(('langchain', 'langgraph')))))",
        ],
        cwd=backend_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ""


@pytest.mark.asyncio
async def test_worker_pool_runs_in_process_and_emits_cancellation() -> None:
    provider = ScriptedProvider(((SlowStream(1), TerminalError("late", "must not arrive")),))
    pool = TaskWorkerPool(max_workers=1)
    events = []

    async def sink(event: object) -> None:
        events.append(event)

    task = pool.submit(provider, request(), sink)
    await asyncio.sleep(0)
    assert await pool.cancel(provider, "request-1") is True
    with pytest.raises(asyncio.CancelledError):
        await task

    assert events == [Cancelled()]
    assert pool.active_request_ids == ()


@pytest.mark.asyncio
async def test_worker_pool_cleans_up_and_notifies_when_cancelled_before_first_tick() -> None:
    provider = ScriptedProvider(((SlowStream(1),),))
    pool = TaskWorkerPool()
    events = []

    async def sink(event: object) -> None:
        events.append(event)

    task = pool.submit(provider, request("race"), sink)
    assert await pool.cancel(provider, "race") is True
    with pytest.raises(asyncio.CancelledError):
        await task

    assert events == [Cancelled()]
    assert pool.active_request_ids == ()


@pytest.mark.asyncio
async def test_worker_pool_cancels_even_when_event_delivery_fails() -> None:
    provider = ScriptedProvider(((SlowStream(1),),))
    pool = TaskWorkerPool()

    async def failing_sink(_: object) -> None:
        raise RuntimeError("client disconnected")

    task = pool.submit(provider, request("failing-sink"), failing_sink)
    assert await pool.cancel(provider, "failing-sink") is True
    with pytest.raises(asyncio.CancelledError):
        await task

    assert pool.active_request_ids == ()


@pytest.mark.asyncio
async def test_worker_pool_enforces_its_concurrency_capacity() -> None:
    class BlockingProvider:
        def __init__(self) -> None:
            self.first_started = asyncio.Event()
            self.second_started = asyncio.Event()
            self.release_first = asyncio.Event()

        async def stream(self, active_request: ProviderRequest):
            if active_request.request_id == "first":
                self.first_started.set()
                await self.release_first.wait()
            else:
                self.second_started.set()
            yield Finished()

        async def cancel(self, _: str) -> None:
            return None

    provider = BlockingProvider()
    pool = TaskWorkerPool(max_workers=1)

    async def sink(_: object) -> None:
        return None

    first = pool.submit(provider, request("first"), sink)
    await provider.first_started.wait()
    second = pool.submit(provider, request("second"), sink)
    await asyncio.sleep(0)
    assert not provider.second_started.is_set()
    provider.release_first.set()
    await asyncio.gather(first, second)
    assert provider.second_started.is_set()
    assert pool.active_request_ids == ()


@pytest.mark.asyncio
async def test_worker_pool_records_context_metadata_before_streaming() -> None:
    provider = ScriptedProvider(((Finished(),),))
    pool = TaskWorkerPool()
    recorded: list[ContextSelectionMetadata] = []
    metadata = ContextSelectionMetadata(
        selected_event_ids=("event-1",),
        selected_artifact_ids=(),
        included_sections=("goal",),
        truncated_sections=(),
        character_count=20,
        selection_fingerprint="a" * 64,
    )

    async def sink(_: object) -> None:
        return None

    async def record(value: ContextSelectionMetadata) -> None:
        recorded.append(value)

    await pool.submit(
        provider, request(), sink, context_metadata=metadata, context_metadata_sink=record
    )

    assert recorded == [metadata]
