"""Deterministic provider double for runtime and integration tests."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class SlowStream:
    """Wait before emitting the next action without introducing nondeterminism."""

    delay_seconds: float


@dataclass(frozen=True)
class Disconnect:
    summary: str = "The provider connection closed unexpectedly."
    retry_after_ms: int | None = None


@dataclass(frozen=True)
class MalformedAction:
    """Models an invalid action payload; caller-side schema validation must reject it."""

    value: JsonValue


ScriptAction = ProviderEvent | SlowStream | Disconnect | MalformedAction


@dataclass
class ScriptedProvider(Provider):
    """Consumes one scripted action sequence per request, without network access."""

    scripts: Iterable[Iterable[ScriptAction]] = ()
    requests: list[ProviderRequest] = field(default_factory=list)
    _pending: deque[tuple[ScriptAction, ...]] = field(init=False)
    _cancelled: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        self._pending = deque(tuple(script) for script in self.scripts)

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        if not self._pending:
            yield TerminalError(code="script_exhausted", summary="No scripted provider response remains.")
            return

        for action in self._pending.popleft():
            if request.request_id in self._cancelled:
                yield Cancelled()
                return
            if isinstance(action, SlowStream):
                await asyncio.sleep(action.delay_seconds)
                continue
            if isinstance(action, Disconnect):
                yield RetryableError("provider_disconnected", action.summary, action.retry_after_ms)
                return
            if isinstance(action, MalformedAction):
                yield StructuredOutput(action.value)
                continue
            yield action

    async def cancel(self, request_id: str) -> None:
        self._cancelled.add(request_id)


def tool_request(call_id: str, name: str, arguments: Mapping[str, JsonValue]) -> ToolCall:
    """Small readable helper for provider scripts."""

    return ToolCall(call_id=call_id, name=name, arguments=arguments)


def deterministic_usage(input_tokens: int, output_tokens: int, *, cost_usd: float | None = None) -> Usage:
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cost_usd=cost_usd,
        exact=True,
    )
