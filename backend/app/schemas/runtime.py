"""Public, bounded runtime observability contracts."""

from typing import Literal

from pydantic import Field

from app.schemas.session_events import CamelModel, Identifier


class RuntimeCheckResponse(CamelModel):
    code: Identifier
    status: Literal["ok", "degraded"]
    summary: str = Field(min_length=1, max_length=500)
    action: str | None = Field(default=None, max_length=500)


class RuntimeQueueResponse(CamelModel):
    runnable_assignments: int = Field(ge=0)
    active_tool_executions: int = Field(ge=0)
    active_provider_operations: int = Field(ge=0)
    pending_approvals: int = Field(ge=0)
    pending_decisions: int = Field(ge=0)
    reserved_limits: int = Field(ge=0)


class WriterLeaseStatusResponse(CamelModel):
    active: int = Field(ge=0)
    expired_unreleased: int = Field(ge=0)


class ProviderLatencyResponse(CamelModel):
    operation_kind: str = Field(min_length=1, max_length=160)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    average_latency_ms: int | None = Field(default=None, ge=0)
    maximum_latency_ms: int | None = Field(default=None, ge=0)


class EventLagResponse(CamelModel):
    newest_event_age_ms: int | None = Field(default=None, ge=0)
    sessions_with_events: int = Field(ge=0)
    invalid_payloads: int = Field(ge=0)


class UsageDiagnosticsResponse(CamelModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    normalized_cost: float | None = Field(default=None, ge=0)
    duration_ms: int = Field(ge=0)
    samples: int = Field(ge=0)


class RuntimeHealthResponse(CamelModel):
    status: Literal["healthy", "degraded"]
    observed_at_ms: int = Field(ge=0)
    checks: list[RuntimeCheckResponse] = Field(max_length=20)
    queues: RuntimeQueueResponse
    writer_leases: WriterLeaseStatusResponse
    provider_latency: list[ProviderLatencyResponse] = Field(max_length=100)
    event_lag: EventLagResponse
    usage: UsageDiagnosticsResponse


class SupportBundleSessionResponse(CamelModel):
    session_id: Identifier
    status: Identifier
    last_sequence: int = Field(ge=0)
    event_counts: dict[str, int] = Field(default_factory=dict, max_length=100)
    configuration_shape: dict[str, object]


class SupportBundleLogResponse(CamelModel):
    timestamp_ms: int = Field(ge=0)
    level: Literal["INFO", "WARNING", "ERROR"]
    event: Identifier
    details: dict[str, object]


class SupportBundleResponse(CamelModel):
    format_version: Literal[1]
    created_at_ms: int = Field(ge=0)
    runtime: RuntimeHealthResponse
    sessions: list[SupportBundleSessionResponse] = Field(max_length=25)
    logs: list[SupportBundleLogResponse] = Field(max_length=200)
    excluded: list[str] = Field(min_length=1, max_length=20)
