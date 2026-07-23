"""REST models for durable local project registration."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from app.schemas.session_events import CamelModel, Identifier


class WorkspaceMode(str, Enum):
    worktree = "worktree"
    snapshot = "snapshot"
    direct_write = "direct_write"


class ProjectRegisterRequest(CamelModel):
    path: str = Field(min_length=1, max_length=4096)
    display_name: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("path")
    @classmethod
    def reject_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("path must not contain NUL")
        return value


class GitMetadataResponse(CamelModel):
    is_git: bool
    root_path: str | None = None
    head: str | None = None
    dirty: bool = False
    nested_repository_paths: list[str] = Field(default_factory=list)
    contains_symlinks: bool = False
    case_sensitive: bool


class ProjectResponse(CamelModel):
    id: Identifier
    canonical_path: str
    display_name: str
    git_metadata: GitMetadataResponse
    created_at_ms: int
    updated_at_ms: int
