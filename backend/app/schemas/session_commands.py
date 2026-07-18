"""Canonical, versioned shared-room client command wire contracts."""

from typing import Annotated, Any, Literal, Union

from pydantic import Field, TypeAdapter, model_validator

from app.schemas.session_events import CamelModel, Content, Identifier, Summary


class CommandEnvelope(CamelModel):
    command_id: Identifier


class MessageSendPayload(CamelModel):
    content: Content
    mention_ids: list[Identifier] = Field(default_factory=list, max_length=50)


class MessageSendCommand(CommandEnvelope):
    type: Literal["message.send"]
    payload: MessageSendPayload


class EmptyPayload(CamelModel):
    pass


class SessionStartCommand(CommandEnvelope):
    type: Literal["session.start"]
    payload: EmptyPayload


class SessionPauseCommand(CommandEnvelope):
    type: Literal["session.pause"]
    payload: EmptyPayload


class SessionResumeCommand(CommandEnvelope):
    type: Literal["session.resume"]
    payload: EmptyPayload


class SessionCancelPayload(CamelModel):
    reason_summary: Summary | None = None


class SessionCancelCommand(CommandEnvelope):
    type: Literal["session.cancel"]
    payload: SessionCancelPayload


class ParticipantInterruptPayload(CamelModel):
    participant_id: Identifier
    reason_summary: Summary


class ParticipantInterruptCommand(CommandEnvelope):
    type: Literal["participant.interrupt"]
    payload: ParticipantInterruptPayload


class ApprovalResolvePayload(CamelModel):
    approval_id: Identifier
    resolution: Literal["approve", "reject", "grant"]
    grant_capabilities: list[Identifier] = Field(default_factory=list, max_length=50)
    scope_summary: Summary | None = None

    @model_validator(mode="after")
    def validate_grant_scope(self) -> "ApprovalResolvePayload":
        if self.resolution == "grant":
            if not self.grant_capabilities:
                raise ValueError("grantCapabilities is required when resolution is grant")
            if self.scope_summary is None:
                raise ValueError("scopeSummary is required when resolution is grant")
        elif "grant_capabilities" in self.model_fields_set:
            raise ValueError("grantCapabilities is only allowed when resolution is grant")
        return self


class ApprovalResolveCommand(CommandEnvelope):
    type: Literal["approval.resolve"]
    payload: ApprovalResolvePayload


class RequiredRoleRulePatch(CamelModel):
    id: Identifier
    role: Identifier
    applicability: Literal["always", "when_changes", "when_capability_used"]
    capability: Identifier | None = None
    success_evidence: Identifier
    minimum_completions: int = Field(ge=1)

    @model_validator(mode="after")
    def require_capability_when_applicable(self) -> "RequiredRoleRulePatch":
        if self.applicability == "when_capability_used" and self.capability is None:
            raise ValueError("capability is required when applicability is when_capability_used")
        if self.applicability != "when_capability_used" and self.capability is not None:
            raise ValueError("capability is only allowed when applicability is when_capability_used")
        return self


class SessionConfigurationPatch(CamelModel):
    available_agent_ids: list[Identifier] | None = Field(default=None, max_length=100)
    required_role_rules: list[RequiredRoleRulePatch] | None = Field(default=None, max_length=50)
    approval_behavior: Literal[
        "ask_each_time", "ask_by_policy", "preauthorize_session", "deny_interactive"
    ] | None = None
    limit_resolution: Literal["ask_user", "coordinator_decides", "stop"] | None = None

    @model_validator(mode="after")
    def require_a_change(self) -> "SessionConfigurationPatch":
        if not self.model_fields_set:
            raise ValueError("patch must change at least one field")
        return self


class SessionConfigurationUpdatePayload(CamelModel):
    expected_configuration_version: int = Field(ge=0)
    patch: SessionConfigurationPatch
    confirm_consequences: bool = False


class SessionConfigurationUpdateCommand(CommandEnvelope):
    type: Literal["session.configuration.update"]
    payload: SessionConfigurationUpdatePayload


class DecisionResolvePayload(CamelModel):
    decision_id: Identifier
    choice: Literal["reassign", "change_approach", "deliver_partial", "stop"]
    reason_summary: Summary | None = None


class DecisionResolveCommand(CommandEnvelope):
    type: Literal["decision.resolve"]
    payload: DecisionResolvePayload


ArgusSessionCommand = Annotated[
    Union[
        MessageSendCommand, SessionStartCommand, SessionPauseCommand, SessionResumeCommand,
        SessionCancelCommand, ParticipantInterruptCommand, ApprovalResolveCommand,
        SessionConfigurationUpdateCommand, DecisionResolveCommand,
    ],
    Field(discriminator="type"),
]

COMMAND_ADAPTER = TypeAdapter(ArgusSessionCommand)


def parse_session_command(value: Any) -> ArgusSessionCommand:
    """Validate one untrusted canonical client command."""
    return COMMAND_ADAPTER.validate_python(value)


def command_schema() -> dict[str, Any]:
    """Return JSON Schema for client command validation tooling."""
    return COMMAND_ADAPTER.json_schema()
