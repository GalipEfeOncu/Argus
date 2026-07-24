"""Provider-neutral streaming contract used by Argus task workers.

This module deliberately contains only standard-library types.  Importing the
sidecar must not import a provider SDK (or an agent-loop implementation) until
that provider is actually selected for a worker.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True)
class ProviderRequest:
    """The bounded, credential-free input supplied to a provider adapter."""

    request_id: str
    model_id: str
    messages: tuple[Mapping[str, str], ...]
    tools: tuple[Mapping[str, JsonValue], ...] = ()
    response_schema: Mapping[str, JsonValue] | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class StructuredOutput:
    """A provider's complete structured response, validated by the caller."""

    value: JsonValue


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, JsonValue]


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    exact: bool = True


@dataclass(frozen=True)
class Finished:
    reason: Literal["stop", "length", "tool_call", "content_filter", "unknown"] = "stop"


@dataclass(frozen=True)
class Cancelled:
    reason: str = "cancelled"


@dataclass(frozen=True)
class RetryableError:
    code: str
    summary: str
    retry_after_ms: int | None = None


@dataclass(frozen=True)
class TerminalError:
    code: str
    summary: str


ProviderEvent: TypeAlias = (
    TextDelta | StructuredOutput | ToolCall | Usage | Finished | Cancelled | RetryableError | TerminalError
)


class Provider(Protocol):
    """A normalized provider implementation.  It never exposes credentials."""

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]: ...

    async def cancel(self, request_id: str) -> None: ...
