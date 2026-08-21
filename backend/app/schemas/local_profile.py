"""Strict REST contracts for the singleton offline local profile."""

from __future__ import annotations

import unicodedata

from pydantic import Field, field_validator, model_validator

from app.schemas.session_events import CamelModel


def _reject_control_characters(value: str) -> str:
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("value must not contain control characters")
    return value


class LocalProfilePatch(CamelModel):
    # A non-validating default makes the field optional for PATCH while keeping
    # explicit JSON null invalid and the generated wire type non-nullable.
    display_name: str = Field(default=None, min_length=1, max_length=80)  # type: ignore[assignment]
    bio: str | None = Field(default=None, max_length=280)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        return _reject_control_characters(value)

    @field_validator("bio", mode="before")
    @classmethod
    def normalize_bio(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("bio")
    @classmethod
    def validate_bio(cls, value: str | None) -> str | None:
        return None if value is None else _reject_control_characters(value)

    @model_validator(mode="after")
    def require_non_empty_patch(self) -> "LocalProfilePatch":
        if not self.model_fields_set:
            raise ValueError("profile patch must contain at least one field")
        return self


class LocalProfileResponse(CamelModel):
    display_name: str = Field(min_length=1, max_length=80)
    bio: str | None = Field(max_length=280)
    created_at_ms: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)


class LocalProfileStateResponse(CamelModel):
    profile: LocalProfileResponse | None
