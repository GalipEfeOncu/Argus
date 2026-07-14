"""Versioned, server-authoritative shared-room event contracts.

The runtime migration will emit these events over WebSocket. Keeping the
discriminated union here lets FastAPI/Pydantic publish the schema used by the
frontend type generator and simulator.
"""

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class EventEnvelope(CamelModel):
    version: Literal[1] = 1
    event_id: str
    session_id: str
    sequence: int = Field(ge=0)
    timestamp: float
    actor_id: str
    correlation_id: str | None = None


class SessionSnapshotPayload(CamelModel):
    status: str
    last_sequence: int = Field(ge=0)


class SessionSnapshotEvent(EventEnvelope):
    type: Literal["session.snapshot"]
    payload: SessionSnapshotPayload


class SessionStatusPayload(CamelModel):
    status: str
    reason: str | None = None


class SessionStatusEvent(EventEnvelope):
    type: Literal["session.status_changed"]
    payload: SessionStatusPayload


class ParticipantStatusPayload(CamelModel):
    role: str
    status: str
    action: str | None = None


class ParticipantStatusEvent(EventEnvelope):
    type: Literal["participant.status_changed"]
    payload: ParticipantStatusPayload


class MessageCreatedPayload(CamelModel):
    message_id: str
    role: Literal["agent", "user", "system"]
    agent_role: str | None = None
    content: str
    streaming: bool = False


class MessageCreatedEvent(EventEnvelope):
    type: Literal["message.created"]
    payload: MessageCreatedPayload


class MessageDeltaPayload(CamelModel):
    message_id: str
    content: str


class MessageDeltaEvent(EventEnvelope):
    type: Literal["message.delta"]
    payload: MessageDeltaPayload


class MessageCompletedPayload(CamelModel):
    message_id: str


class MessageCompletedEvent(EventEnvelope):
    type: Literal["message.completed"]
    payload: MessageCompletedPayload


class ToolCallPayload(CamelModel):
    id: str
    tool: str
    args: dict[str, Any]
    status: Literal["pending", "running", "success", "error"]


class ToolEventPayload(CamelModel):
    message_id: str
    role: str
    tool_call: ToolCallPayload


class ToolRequestedEvent(EventEnvelope):
    type: Literal["tool.requested", "tool.started"]
    payload: ToolEventPayload


class ToolCompletedPayload(CamelModel):
    message_id: str
    tool_call_id: str
    result: str
    duration: int | None = Field(default=None, ge=0)
    success: bool


class ToolCompletedEvent(EventEnvelope):
    type: Literal["tool.completed"]
    payload: ToolCompletedPayload


class ApprovalPayload(CamelModel):
    approval_id: str
    reason: str
    message: str
    requested_by: str


class ApprovalEvent(EventEnvelope):
    type: Literal["approval.requested", "approval.resolved"]
    payload: ApprovalPayload


class DiffPayload(CamelModel):
    message_id: str
    file_path: str
    before: str
    after: str
    additions: int
    deletions: int


class DiffEvent(EventEnvelope):
    type: Literal["artifact.diff_updated"]
    payload: DiffPayload


class UsagePayload(CamelModel):
    role: str
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost: float | None = Field(default=None, ge=0)


class UsageEvent(EventEnvelope):
    type: Literal["usage.updated"]
    payload: UsagePayload


class ErrorPayload(CamelModel):
    message: str
    recoverable: bool


class ErrorEvent(EventEnvelope):
    type: Literal["error.created"]
    payload: ErrorPayload


ArgusSessionEvent = Annotated[
    Union[
        SessionSnapshotEvent,
        SessionStatusEvent,
        ParticipantStatusEvent,
        MessageCreatedEvent,
        MessageDeltaEvent,
        MessageCompletedEvent,
        ToolRequestedEvent,
        ToolCompletedEvent,
        ApprovalEvent,
        DiffEvent,
        UsageEvent,
        ErrorEvent,
    ],
    Field(discriminator="type"),
]


def event_schema() -> dict[str, Any]:
    """Return JSON Schema for client type generation and contract checks."""
    return TypeAdapter(ArgusSessionEvent).json_schema()
