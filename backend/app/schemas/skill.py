"""Strict local skill-package REST and manifest models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from app.schemas.session_events import CamelModel, Identifier


class SkillManifest(CamelModel):
    schema_version: Literal[1]
    id: Identifier
    name: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=4_000)
    instructions: str = Field(min_length=1, max_length=512)
    references: list[str] = Field(default_factory=list, max_length=100)
    requested_tools: list[Identifier] = Field(default_factory=list, max_length=50)
    requested_permissions: list[Identifier] = Field(default_factory=list, max_length=50)

    @field_validator("instructions", "references")
    @classmethod
    def reject_absolute_or_empty_paths(cls, value: str | list[str]) -> str | list[str]:
        values = [value] if isinstance(value, str) else value
        if any(not item or item.startswith(("/", "\\")) or "\\" in item for item in values):
            raise ValueError("skill package paths must be non-empty relative POSIX paths")
        return value


class SkillImportRequest(CamelModel):
    source_path: str = Field(min_length=1, max_length=4096)


class SkillEnableRequest(CamelModel):
    enabled: bool


class SkillPackageResponse(CamelModel):
    id: Identifier
    manifest: SkillManifest
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trust_state: Literal["review_required", "enabled"]
    source_path: str
    enabled: bool
    created_at_ms: int = Field(ge=0)
    requested_tools: list[Identifier]
    requested_permissions: list[Identifier]
