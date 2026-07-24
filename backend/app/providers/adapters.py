"""Lazy factories for optional production provider dependency groups."""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator, Callable, Mapping
from typing import TYPE_CHECKING, Literal

from app.providers.protocol import (
    Cancelled,
    Finished,
    JsonValue,
    Provider,
    ProviderEvent,
    ProviderRequest,
    RetryableError,
    StructuredOutput,
    TerminalError,
    TextDelta,
    ToolCall,
    Usage,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

ProviderKind = Literal["openai", "openai_compat", "anthropic", "google"]
ModuleLoader = Callable[[str], object]


class ProviderDependencyUnavailable(RuntimeError):
    """Raised only when a configured provider's optional package is missing."""


class LangChainProvider(Provider):
    """Adapt one lazily-created chat model to the Argus streaming contract."""

    def __init__(self, model: "BaseChatModel") -> None:
        self._model = model
        self._cancelled_request_ids: set[str] = set()

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        finish_reason = "unknown"
        try:
            model = self._prepared_model(request)
            async for chunk in model.astream(list(request.messages)):
                if request.request_id in self._cancelled_request_ids:
                    yield Cancelled()
                    return
                for event in self._chunk_events(chunk):
                    yield event
                response_metadata = getattr(chunk, "response_metadata", {}) or {}
                candidate = response_metadata.get("finish_reason")
                if isinstance(candidate, str):
                    finish_reason = candidate
            if request.request_id in self._cancelled_request_ids:
                yield Cancelled()
                return
            yield Finished(reason=_finish_reason(finish_reason))
        except ProviderRequestUnsupported:
            yield TerminalError("provider_request_unsupported", "The configured provider cannot satisfy this request.")
        except Exception as error:
            if _is_retryable(error):
                yield RetryableError("provider_unavailable", "The provider is temporarily unavailable.")
            else:
                yield TerminalError("provider_error", "The provider could not complete this request.")

    async def cancel(self, request_id: str) -> None:
        # Task cancellation stops the in-flight coroutine.  This marker also
        # prevents a provider from yielding a buffered chunk after cancellation.
        self._cancelled_request_ids.add(request_id)

    @staticmethod
    def _chunk_events(chunk: object) -> tuple[ProviderEvent, ...]:
        if isinstance(chunk, Mapping) and "raw" in chunk:
            events = list(LangChainProvider._chunk_events(chunk["raw"]))
            parsed = chunk.get("parsed")
            if _is_json_value(parsed):
                events.append(StructuredOutput(parsed))
            return tuple(events)
        if _is_json_value(chunk) and not isinstance(chunk, str):
            return (StructuredOutput(chunk),)
        events: list[ProviderEvent] = []
        text = _chunk_text(getattr(chunk, "content", ""))
        if text:
            events.append(TextDelta(text))
        for call in getattr(chunk, "tool_calls", ()) or ():
            if not isinstance(call, Mapping):
                continue
            name = call.get("name")
            call_id = call.get("id")
            arguments = call.get("args", {})
            if isinstance(name, str) and isinstance(call_id, str) and isinstance(arguments, Mapping):
                events.append(ToolCall(call_id, name, dict(arguments)))
        additional = getattr(chunk, "additional_kwargs", {}) or {}
        parsed = additional.get("parsed") if isinstance(additional, Mapping) else None
        if parsed is not None:
            events.append(StructuredOutput(parsed))
        usage = getattr(chunk, "usage_metadata", {}) or {}
        if isinstance(usage, Mapping) and usage:
            events.append(Usage(
                input_tokens=_integer_or_none(usage.get("input_tokens")),
                output_tokens=_integer_or_none(usage.get("output_tokens")),
                total_tokens=_integer_or_none(usage.get("total_tokens")),
                exact=True,
            ))
        return tuple(events)

    def _prepared_model(self, request: ProviderRequest) -> object:
        model: object = self._model
        if request.tools:
            bind_tools = getattr(model, "bind_tools", None)
            if not callable(bind_tools):
                raise ProviderRequestUnsupported
            model = bind_tools(list(request.tools))
        if request.response_schema is not None:
            structured_output = getattr(model, "with_structured_output", None)
            if not callable(structured_output):
                raise ProviderRequestUnsupported
            model = structured_output(dict(request.response_schema), include_raw=True)
        if not callable(getattr(model, "astream", None)):
            raise ProviderRequestUnsupported
        return model


def create_chat_model(
    provider_kind: ProviderKind,
    *,
    model_id: str,
    api_key: str,
    base_url: str | None = None,
    module_loader: ModuleLoader = importlib.import_module,
) -> "BaseChatModel":
    """Create exactly one configured adapter, importing only its SDK on demand."""

    try:
        if provider_kind == "anthropic":
            module = module_loader("langchain_anthropic")
            return module.ChatAnthropic(model=model_id, api_key=api_key, streaming=True, max_tokens=8096)
        if provider_kind == "google":
            module = module_loader("langchain_google_genai")
            return module.ChatGoogleGenerativeAI(model=model_id, google_api_key=api_key, streaming=True)

        module = module_loader("langchain_openai")
        kwargs: dict[str, object] = {"model": model_id, "api_key": api_key, "streaming": True}
        if base_url:
            kwargs["base_url"] = base_url
        return module.ChatOpenAI(**kwargs)
    except ModuleNotFoundError as exc:
        raise ProviderDependencyUnavailable(
            f"The optional provider dependency group for '{provider_kind}' is not installed."
        ) from exc


def create_provider(
    provider_kind: ProviderKind,
    *,
    model_id: str,
    api_key: str,
    base_url: str | None = None,
    module_loader: ModuleLoader = importlib.import_module,
) -> Provider:
    """Create the production provider used directly by in-process workers."""

    return LangChainProvider(create_chat_model(
        provider_kind,
        model_id=model_id,
        api_key=api_key,
        base_url=base_url,
        module_loader=module_loader,
    ))


def _chunk_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    text: list[str] = []
    for part in content:
        if isinstance(part, str):
            text.append(part)
        elif isinstance(part, Mapping) and isinstance(part.get("text"), str):
            text.append(part["text"])
    return "".join(text)


def _integer_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _finish_reason(value: str) -> Literal["stop", "length", "tool_call", "content_filter", "unknown"]:
    return value if value in {"stop", "length", "tool_call", "content_filter"} else "unknown"


def _is_retryable(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    return status_code == 429 or isinstance(status_code, int) and status_code >= 500


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False


class ProviderRequestUnsupported(Exception):
    """An optional SDK cannot bind requested tools or a response schema."""
