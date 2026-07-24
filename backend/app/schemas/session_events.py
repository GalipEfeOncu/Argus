"""Canonical, versioned shared-room server event wire contracts.

These models are intentionally not wired into the legacy WebSocket transport
yet.  They are the authoritative target schema used for generated clients and
fixture validation during the transport migration.
"""

from datetime import datetime
import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator
from pydantic.alias_generators import to_camel


Identifier = Annotated[str, Field(min_length=1, max_length=160)]
Summary = Annotated[str, Field(min_length=1, max_length=4_000)]
Content = Annotated[str, Field(min_length=1, max_length=64_000)]
TIMEZONE_AWARE_ISO_TIMESTAMP_PATTERN = (
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
SAFE_RELATIVE_ARTIFACT_PATH_PATTERN = (
    r"^(?![\\/])(?![A-Za-z]:)(?!\.\.(?:[\\/]|$))(?!.*[\\/]\.\.(?:[\\/]|$)).+$"
)


class CamelModel(BaseModel):
    """Strict JSON model whose public wire names are camelCase."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=False,
        extra="forbid",
        str_strip_whitespace=True,
    )


class EventEnvelope(CamelModel):
    version: Literal[1]
    event_id: Identifier
    session_id: Identifier
    sequence: int = Field(ge=0)
    timestamp: datetime = Field(json_schema_extra={"pattern": TIMEZONE_AWARE_ISO_TIMESTAMP_PATTERN})
    actor_id: Identifier
    correlation_id: Identifier | None = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def require_timezone_aware_iso_timestamp(cls, value: object) -> object:
        if not isinstance(value, str) or not re.fullmatch(TIMEZONE_AWARE_ISO_TIMESTAMP_PATTERN, value):
            raise ValueError("timestamp must be timezone-aware ISO-8601 text")
        return value


class Evidence(CamelModel):
    kind: Identifier
    summary: Summary
    artifact_ids: list[Identifier] = Field(default_factory=list, max_length=50)


class SessionSnapshotPayload(CamelModel):
    status: Literal[
        "created", "preparing", "running", "paused", "waiting_approval",
        "waiting_decision", "completed", "completed_partial", "cancelled", "failed",
    ]
    last_sequence: int = Field(ge=0)


class SessionSnapshotEvent(EventEnvelope):
    type: Literal["session.snapshot"]
    payload: SessionSnapshotPayload


class SessionStatusPayload(CamelModel):
    status: Literal[
        "created", "preparing", "running", "paused", "waiting_approval",
        "waiting_decision", "completed", "completed_partial", "cancelled", "failed",
    ]
    reason_summary: Summary | None = None


class SessionStatusChangedEvent(EventEnvelope):
    type: Literal["session.status_changed"]
    payload: SessionStatusPayload


class ParticipantStatusPayload(CamelModel):
    participant_id: Identifier
    participant_kind: Literal["human", "system", "coordinator", "agent"]
    status: Literal["idle", "working", "waiting", "paused", "errored", "stopped"]
    action_summary: Summary | None = None


class ParticipantStatusChangedEvent(EventEnvelope):
    type: Literal["participant.status_changed"]
    payload: ParticipantStatusPayload


class MessageCreatedPayload(CamelModel):
    message_id: Identifier
    author_id: Identifier
    author_kind: Literal["human", "system", "coordinator", "agent"]
    content: Content
    mention_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    streaming: bool = False


class MessageCreatedEvent(EventEnvelope):
    type: Literal["message.created"]
    payload: MessageCreatedPayload


class MessageDeltaPayload(CamelModel):
    message_id: Identifier
    delta: Content


class MessageDeltaEvent(EventEnvelope):
    type: Literal["message.delta"]
    payload: MessageDeltaPayload


class MessageCompletedPayload(CamelModel):
    message_id: Identifier


class MessageCompletedEvent(EventEnvelope):
    type: Literal["message.completed"]
    payload: MessageCompletedPayload


class ConfigurationUpdatedPayload(CamelModel):
    configuration_version: int = Field(ge=0)
    previous_policy_hash: Identifier
    policy_hash: Identifier
    changed_fields: list[Identifier] = Field(min_length=1, max_length=20)


class SessionConfigurationUpdatedEvent(EventEnvelope):
    type: Literal["session.configuration_updated"]
    payload: ConfigurationUpdatedPayload


class AssignmentProposedPayload(CamelModel):
    proposal_id: Identifier
    assignee_agent_id: Identifier
    parent_id: Identifier | None = None
    objective: Summary
    acceptance_criteria: list[Summary] = Field(min_length=1, max_length=50)
    operation_class: Literal["read_only", "mutating"]
    requested_capabilities: list[Identifier] = Field(default_factory=list, max_length=50)
    reason_summary: Summary


class AssignmentProposedEvent(EventEnvelope):
    type: Literal["assignment.proposed"]
    payload: AssignmentProposedPayload


class AssignmentCreatedPayload(CamelModel):
    assignment_id: Identifier
    proposal_id: Identifier
    assignee_agent_id: Identifier
    configuration_version: int = Field(ge=0)
    policy_hash: Identifier
    operation_class: Literal["read_only", "mutating"]


class AssignmentCreatedEvent(EventEnvelope):
    type: Literal["assignment.created"]
    payload: AssignmentCreatedPayload


class AssignmentStartedPayload(CamelModel):
    assignment_id: Identifier
    assignee_agent_id: Identifier


class AssignmentStartedEvent(EventEnvelope):
    type: Literal["assignment.started"]
    payload: AssignmentStartedPayload


class AssignmentCompletedPayload(CamelModel):
    assignment_id: Identifier
    status: Literal["completed", "completed_partial"]
    output_summary: Summary
    evidence: list[Evidence] = Field(default_factory=list, max_length=50)


class AssignmentCompletedEvent(EventEnvelope):
    type: Literal["assignment.completed"]
    payload: AssignmentCompletedPayload


class AssignmentFailedPayload(CamelModel):
    assignment_id: Identifier
    failure_code: Identifier
    failure_summary: Summary
    recoverable: bool


class AssignmentFailedEvent(EventEnvelope):
    type: Literal["assignment.failed"]
    payload: AssignmentFailedPayload


class AssignmentCancelledPayload(CamelModel):
    assignment_id: Identifier
    reason_summary: Summary


class AssignmentCancelledEvent(EventEnvelope):
    type: Literal["assignment.cancelled"]
    payload: AssignmentCancelledPayload


class HandoffCreatedPayload(CamelModel):
    handoff_id: Identifier
    source_assignment_id: Identifier
    target_agent_id: Identifier | None = None
    summary: Summary
    artifact_ids: list[Identifier] = Field(default_factory=list, max_length=50)


class HandoffCreatedEvent(EventEnvelope):
    type: Literal["handoff.created"]
    payload: HandoffCreatedPayload


class ToolRequestedPayload(CamelModel):
    tool_execution_id: Identifier
    assignment_id: Identifier
    tool_name: Identifier
    operation_class: Literal["read_only", "mutating"]
    request_summary: Summary


class ToolRequestedEvent(EventEnvelope):
    type: Literal["tool.requested"]
    payload: ToolRequestedPayload


class ToolStartedPayload(CamelModel):
    tool_execution_id: Identifier
    assignment_id: Identifier
    tool_name: Identifier


class ToolStartedEvent(EventEnvelope):
    type: Literal["tool.started"]
    payload: ToolStartedPayload


class ToolCompletedPayload(CamelModel):
    tool_execution_id: Identifier
    assignment_id: Identifier
    status: Literal["succeeded", "failed", "cancelled"]
    result_summary: Summary
    duration_ms: int = Field(ge=0)
    artifact_ids: list[Identifier] = Field(default_factory=list, max_length=50)


class ToolCompletedEvent(EventEnvelope):
    type: Literal["tool.completed"]
    payload: ToolCompletedPayload


class ApprovalRequestedPayload(CamelModel):
    approval_id: Identifier
    assignment_id: Identifier | None = None
    capability: Identifier
    scope_summary: Summary


class ApprovalRequestedEvent(EventEnvelope):
    type: Literal["approval.requested"]
    payload: ApprovalRequestedPayload


class ApprovalResolvedPayload(CamelModel):
    approval_id: Identifier
    resolution: Literal["approved", "rejected", "granted"]
    grant_id: Identifier | None = None
    reason_summary: Summary | None = None


class ApprovalResolvedEvent(EventEnvelope):
    type: Literal["approval.resolved"]
    payload: ApprovalResolvedPayload


class LimitPayload(CamelModel):
    counter: Literal[
        "revisions", "assignment_attempts", "model_iterations", "tool_calls",
        "wall_clock_seconds", "tokens", "cost", "parallel_read_only_assignments",
    ]
    scope_id: Identifier
    current: float = Field(ge=0)
    threshold: float = Field(ge=0)
    hard: bool
    resolution: Literal["ask_user", "coordinator_decides", "stop"]
    fingerprint: Identifier | None = None
    occurrence_count: int | None = Field(default=None, ge=1)


class LimitWarningEvent(EventEnvelope):
    type: Literal["limit.warning"]
    payload: LimitPayload


class LimitReachedEvent(EventEnvelope):
    type: Literal["limit.reached"]
    payload: LimitPayload


class DecisionRequestedPayload(CamelModel):
    decision_id: Identifier
    scope_id: Identifier
    choices: list[Literal["reassign", "change_approach", "deliver_partial", "stop"]] = Field(
        min_length=1, max_length=4
    )
    reason_summary: Summary


class DecisionRequestedEvent(EventEnvelope):
    type: Literal["decision.requested"]
    payload: DecisionRequestedPayload


class DecisionRecordedPayload(CamelModel):
    decision_id: Identifier
    choice: Literal["reassign", "change_approach", "deliver_partial", "stop"]
    reason_summary: Summary


class DecisionRecordedEvent(EventEnvelope):
    type: Literal["decision.recorded"]
    payload: DecisionRecordedPayload


class GateStatusPayload(CamelModel):
    gate_id: Identifier
    role: Identifier
    status: Literal["not_applicable", "pending", "satisfied", "failed"]
    evidence: list[Evidence] = Field(default_factory=list, max_length=50)


class GateStatusChangedEvent(EventEnvelope):
    type: Literal["gate.status_changed"]
    payload: GateStatusPayload


class ArtifactDiffUpdatedPayload(CamelModel):
    artifact_id: Identifier
    assignment_id: Identifier | None = None
    file_path: Annotated[
        str,
        Field(
            min_length=1,
            max_length=4_000,
            json_schema_extra={"pattern": SAFE_RELATIVE_ARTIFACT_PATH_PATTERN},
        ),
    ]
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    byte_length: int = Field(ge=0)
    truncated: bool = False

    @field_validator("file_path")
    @classmethod
    def require_safe_relative_artifact_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if (
            value.startswith(("/", "\\"))
            or re.match(r"^[A-Za-z]:", value)
            or any(part == ".." for part in normalized.split("/"))
        ):
            raise ValueError("filePath must be a safe relative artifact path")
        return value


class ArtifactDiffUpdatedEvent(EventEnvelope):
    type: Literal["artifact.diff_updated"]
    payload: ArtifactDiffUpdatedPayload


class UsageUpdatedPayload(CamelModel):
    scope_id: Identifier
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    normalized_cost: float = Field(ge=0)
    duration_ms: int = Field(ge=0)


class UsageUpdatedEvent(EventEnvelope):
    type: Literal["usage.updated"]
    payload: UsageUpdatedPayload


class ErrorCreatedPayload(CamelModel):
    error_id: Identifier
    code: Identifier
    summary: Summary
    recoverable: bool
    related_id: Identifier | None = None


class ErrorCreatedEvent(EventEnvelope):
    type: Literal["error.created"]
    payload: ErrorCreatedPayload


ArgusSessionEvent = Annotated[
    Union[
        SessionSnapshotEvent, SessionStatusChangedEvent, ParticipantStatusChangedEvent,
        MessageCreatedEvent, MessageDeltaEvent, MessageCompletedEvent,
        SessionConfigurationUpdatedEvent, AssignmentProposedEvent, AssignmentCreatedEvent,
        AssignmentStartedEvent, AssignmentCompletedEvent, AssignmentFailedEvent,
        AssignmentCancelledEvent, HandoffCreatedEvent, ToolRequestedEvent, ToolStartedEvent,
        ToolCompletedEvent, ApprovalRequestedEvent, ApprovalResolvedEvent, LimitWarningEvent,
        LimitReachedEvent, DecisionRequestedEvent, DecisionRecordedEvent, GateStatusChangedEvent,
        ArtifactDiffUpdatedEvent, UsageUpdatedEvent, ErrorCreatedEvent,
    ],
    Field(discriminator="type"),
]

EVENT_ADAPTER = TypeAdapter(ArgusSessionEvent)


def parse_session_event(value: Any) -> ArgusSessionEvent:
    """Validate one untrusted canonical server event."""
    return EVENT_ADAPTER.validate_python(value)


def event_schema() -> dict[str, Any]:
    """Return JSON Schema for client type generation and contract checks."""
    return EVENT_ADAPTER.json_schema()
