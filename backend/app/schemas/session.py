"""REST models for durable, versioned session configuration."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.schemas.project import WorkspaceMode
from app.schemas.session_events import CamelModel, Identifier, Summary


class SessionStatus(str, Enum):
    setup = "setup"
    running = "running"
    paused = "paused"
    waiting_approval = "waiting_approval"
    completed = "completed"
    error = "error"


class RoleConfigSchema(CamelModel):
    """Compatibility input for the prototype session launcher."""

    role: str
    enabled: bool = True
    provider_id: str | None = None
    model_id: str | None = None
    custom_system_prompt: str | None = None


PermissionProfile = Literal["strict", "balanced", "autonomous", "expert_unrestricted"]
AgentDefinitionKind = Literal["builtin", "builtin_override", "custom"]


class AgentModelBinding(CamelModel):
    """A non-secret provider/model reference, never provider credentials."""

    provider_profile_id: Identifier
    model_id: Identifier


class AgentDefinitionCreate(CamelModel):
    """The immutable, versioned source for a session agent."""

    name: str = Field(min_length=1, max_length=160)
    kind: AgentDefinitionKind
    base_role: Identifier | None = None
    role: Identifier
    system_prompt: str = Field(min_length=1, max_length=16_000)
    model_binding: AgentModelBinding
    capabilities: list[Identifier] = Field(default_factory=list, max_length=50)
    skill_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    tool_allowlist: list[Identifier] = Field(default_factory=list, max_length=50)
    permission_profile: PermissionProfile = "balanced"
    evidence_schema: dict[str, Any] | None = None
    evidence_kinds: list[Identifier] = Field(default_factory=list, max_length=20)
    output_language: str = Field(default="en", min_length=2, max_length=16)


class AgentDefinitionResponse(AgentDefinitionCreate):
    id: Identifier
    template_version: str = Field(min_length=1, max_length=64)
    created_at_ms: int = Field(ge=0)


class SessionAgentInput(CamelModel):
    id: Identifier
    role: Identifier
    capabilities: list[Identifier] = Field(default_factory=list, max_length=50)
    agent_definition_id: Identifier | None = None
    definition_version: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=16_000)
    model_binding: AgentModelBinding | None = None
    skill_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    tool_allowlist: list[Identifier] = Field(default_factory=list, max_length=50)
    permission_profile: PermissionProfile = "balanced"
    model_snapshot: dict[str, object] = Field(default_factory=dict)
    skill_snapshot: list[object] = Field(default_factory=list, max_length=50)
    evidence_schema: dict[str, Any] | None = None
    evidence_kinds: list[Identifier] = Field(default_factory=list, max_length=20)
    output_language: str | None = Field(default=None, min_length=2, max_length=16)


class RequiredRoleRule(CamelModel):
    id: Identifier
    role: Identifier
    applicability: Literal["always", "when_changes", "when_capability_used"]
    capability: Identifier | None = None
    success_evidence: Identifier
    minimum_completions: int = Field(default=1, ge=1)
    acceptance_fields: list[Identifier] = Field(default_factory=list, max_length=20)
    required_capabilities: list[Identifier] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_capability(self) -> "RequiredRoleRule":
        if self.applicability == "when_capability_used" and self.capability is None:
            raise ValueError("capability is required when applicability is when_capability_used")
        if self.applicability != "when_capability_used" and self.capability is not None:
            raise ValueError("capability is only allowed when applicability is when_capability_used")
        return self


class ExecutionLimits(CamelModel):
    max_revisions_per_finding: int | None = Field(default=3, ge=0)
    max_assignment_attempts: int | None = Field(default=8, ge=0)
    max_model_iterations_per_assignment: int | None = Field(default=20, ge=0)
    max_tool_calls_per_assignment: int | None = Field(default=100, ge=0)
    max_session_tokens: int | None = Field(default=500_000, ge=0)
    max_session_cost: float | None = Field(default=None, ge=0)
    max_wall_clock_seconds: int | None = Field(default=14_400, ge=0)
    max_parallel_read_only_assignments: int | None = Field(default=3, ge=0)
    soft_warning_ratio: float = Field(default=0.8, gt=0, le=1)


class ExecutionLimitsPatch(CamelModel):
    """Partial limit change; omitted fields retain their current ceiling."""

    max_revisions_per_finding: int | None = Field(default=None, ge=0)
    max_assignment_attempts: int | None = Field(default=None, ge=0)
    max_model_iterations_per_assignment: int | None = Field(default=None, ge=0)
    max_tool_calls_per_assignment: int | None = Field(default=None, ge=0)
    max_session_tokens: int | None = Field(default=None, ge=0)
    max_session_cost: float | None = Field(default=None, ge=0)
    max_wall_clock_seconds: int | None = Field(default=None, ge=0)
    max_parallel_read_only_assignments: int | None = Field(default=None, ge=0)
    soft_warning_ratio: float | None = Field(default=None, gt=0, le=1)


class ApprovalPolicy(CamelModel):
    permission_profile: PermissionProfile = "balanced"
    behavior: Literal["ask_each_time", "ask_by_policy", "preauthorize_session", "deny_interactive"] = "ask_by_policy"
    preauthorized_capabilities: list[Identifier] = Field(default_factory=list, max_length=50)
    capability_overrides: dict[Identifier, Literal["allow", "ask", "deny"]] = Field(default_factory=dict, max_length=50)
    limit_resolution: Literal["ask_user", "coordinator_decides", "stop"] = "coordinator_decides"


class WorkspacePolicy(CamelModel):
    mode: WorkspaceMode | None = None


class SessionConfigurationInput(CamelModel):
    available_agent_ids: list[Identifier] | None = Field(default=None, max_length=100)
    required_role_rules: list[RequiredRoleRule] = Field(default_factory=list, max_length=50)
    execution_limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    approval_policy: ApprovalPolicy = Field(default_factory=ApprovalPolicy)
    workspace_policy: WorkspacePolicy = Field(default_factory=WorkspacePolicy)
    acknowledgements: list[Identifier] = Field(default_factory=list, max_length=20)


class SessionCreateRequest(CamelModel):
    # projectPath/task/roleConfigs are preserved while callers move to the
    # documented projectId/goal/agents configuration contract.
    project_id: Identifier | None = None
    project_path: str | None = Field(default=None, min_length=1, max_length=4096)
    goal: Summary | None = None
    task: Summary | None = None
    name: str | None = Field(default=None, min_length=1, max_length=256)
    coordinator_agent_id: Identifier | None = None
    agents: list[SessionAgentInput] = Field(default_factory=list, max_length=100)
    configuration: SessionConfigurationInput = Field(default_factory=SessionConfigurationInput)
    role_configs: list[RoleConfigSchema] = Field(default_factory=list, max_length=100)
    workspace_mode: WorkspaceMode | None = None
    acknowledge_direct_write: bool = False

    # Preserve the prototype's snake_case launcher request while emitting and
    # documenting the canonical camelCase REST contract.
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True, extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def require_project_and_goal(self) -> "SessionCreateRequest":
        if (self.project_id is None) == (self.project_path is None):
            raise ValueError("exactly one of projectId or projectPath is required")
        if (self.goal is None) == (self.task is None):
            raise ValueError("exactly one of goal or task is required")
        return self


class SessionResponse(CamelModel):
    id: Identifier
    name: str
    project_path: str
    task: str
    status: SessionStatus
    started_at: float
    completed_at: float | None = None


class SessionConfigurationResponse(CamelModel):
    configuration_version: int = Field(ge=1)
    available_agent_ids: list[Identifier]
    required_role_rules: list[RequiredRoleRule]
    execution_limits: ExecutionLimits
    approval_policy: ApprovalPolicy
    workspace_policy: WorkspacePolicy
    acknowledgements: list[Identifier]
    policy_hash: str = Field(min_length=64, max_length=64)
    agent_snapshots: list["SessionAgentSnapshotResponse"]


class SessionAgentSnapshotResponse(CamelModel):
    id: Identifier
    source_agent_id: Identifier
    role: Identifier
    capabilities: list[Identifier]
    evidence_schema: dict[str, Any] | None = None
    agent_definition_id: Identifier | None = None
    definition_version: str | None = None
    name: str | None = None
    skill_ids: list[Identifier] = Field(default_factory=list)
    tool_allowlist: list[Identifier] = Field(default_factory=list)
    permission_profile: PermissionProfile = "balanced"
    evidence_kinds: list[Identifier] = Field(default_factory=list)
    output_language: str | None = None


class SessionCreateResponse(SessionConfigurationResponse):
    id: Identifier
    name: str
    project_id: Identifier
    goal: Summary
