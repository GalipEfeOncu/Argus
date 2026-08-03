"""Typed bounded read models for the canonical event-store REST resources."""

from typing import Literal

from pydantic import Field, model_validator

from app.schemas.session_events import ArgusSessionEvent, CamelModel, Identifier


class TimelinePageResponse(CamelModel):
    events: list[ArgusSessionEvent]
    next_after_sequence: int | None = None


class ArtifactSummaryResponse(CamelModel):
    id: Identifier
    kind: Identifier
    relative_path: str | None = None
    checksum: Identifier
    metadata: dict[str, object]
    created_at_ms: int


class ArtifactPageResponse(CamelModel):
    items: list[ArtifactSummaryResponse]
    next_cursor: str | None = None


class AcceptanceFileResponse(CamelModel):
    path: str = Field(min_length=1, max_length=4096)
    change: Literal["added", "modified", "deleted", "binary"]
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    byte_length: int = Field(ge=0)


class AcceptanceGateResponse(CamelModel):
    id: Identifier
    role: Identifier
    status: Identifier
    evidence_count: int = Field(ge=0)


class AcceptanceUsageResponse(CamelModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    normalized_cost: float | None = Field(default=None, ge=0)
    duration_ms: int = Field(ge=0)


class AcceptanceActionResponse(CamelModel):
    id: Identifier
    action: Literal["apply", "reject", "export", "follow_up"]
    disposition: Literal["retain", "cleanup"]
    state: Literal["pending", "waiting_approval", "applying", "applied", "rejected", "exported", "follow_up_started", "drifted", "denied", "failed", "outcome_unknown"]
    summary: str = Field(min_length=1, max_length=4000)
    created_at_ms: int = Field(ge=0)
    completed_at_ms: int | None = Field(default=None, ge=0)


class AcceptanceReviewResponse(CamelModel):
    session_id: Identifier
    workspace_mode: Literal["worktree", "snapshot", "direct_write"]
    workspace_checksum: Identifier
    original_checksum: Identifier | None = None
    current_original_checksum: Identifier | None = None
    drifted: bool
    can_apply: bool
    patch_available: bool
    files: list[AcceptanceFileResponse] = Field(max_length=1000)
    artifacts: list[ArtifactSummaryResponse] = Field(max_length=100)
    gates: list[AcceptanceGateResponse] = Field(max_length=100)
    unmet_gates: list[str] = Field(max_length=100)
    limits: list[dict[str, object]] = Field(max_length=100)
    usage: AcceptanceUsageResponse
    coordinator_summary: str | None = Field(default=None, max_length=4000)
    latest_action: AcceptanceActionResponse | None = None


class AcceptanceActionRequest(CamelModel):
    command_id: Identifier
    action: Literal["apply", "reject", "export", "follow_up"]
    disposition: Literal["retain", "cleanup"]
    expected_original_checksum: Identifier | None = None
    follow_up_goal: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_disposition(self) -> "AcceptanceActionRequest":
        if self.action == "export" and self.disposition != "retain":
            raise ValueError("export retains the workspace so the user can download the generated patch")
        return self


class AcceptancePatchResponse(CamelModel):
    patch: str = Field(max_length=2_000_000)
    checksum: Identifier
