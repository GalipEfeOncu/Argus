"""Non-secret provider-profile REST contracts."""

from __future__ import annotations

from typing import Literal
import re

from pydantic import ConfigDict, Field, HttpUrl, SecretStr, field_validator

from app.schemas.session_events import CamelModel, Identifier, Summary


class ProviderCamelModel(CamelModel):
    model_config = ConfigDict(
        alias_generator=lambda value: "".join([value.split("_")[0], *[part.title() for part in value.split("_")[1:]]]),
        validate_by_name=True,
        validate_by_alias=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


ProviderKind = Literal["openai", "anthropic", "google", "openai_compat"]


class ProviderProfileCreate(ProviderCamelModel):
    provider_kind: ProviderKind
    display_name: str = Field(min_length=1, max_length=160)
    endpoint: str | None = Field(default=None, max_length=2_000)
    credential_reference: str | None = Field(default=None, min_length=8, max_length=256)

    @field_validator("credential_reference")
    @classmethod
    def validate_credential_reference(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"argus-provider-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
            raise ValueError("credential reference must be a native opaque reference")
        return value

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = HttpUrl(value)
        if parsed.username is not None or parsed.password is not None or parsed.fragment is not None:
            raise ValueError("endpoint must not contain credentials or a fragment")
        host = parsed.host or ""
        if parsed.scheme != "https" and host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("endpoint must use HTTPS unless it is a loopback server")
        return str(parsed).rstrip("/")


class ProviderProfileResponse(ProviderCamelModel):
    id: Identifier
    provider_kind: ProviderKind
    display_name: str
    endpoint: str | None = None
    credential_configured: bool
    created_at_ms: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)


class ModelCapability(ProviderCamelModel):
    id: Identifier
    display_name: str
    context_window: int | None = Field(default=None, ge=1)
    supports_tools: bool | None = None
    supports_structured_output: bool | None = None
    source: Literal["discovered", "catalog", "manual"]


class ProviderModelListResponse(ProviderCamelModel):
    models: list[ModelCapability]
    discovery_status: Literal["available", "credential_required", "unavailable"]
    error: Summary | None = None


class ManualModelRequest(ProviderCamelModel):
    model_id: Identifier


class NativeCredentialLeaseRequest(ProviderCamelModel):
    """Native-bridge-only secret envelope. It is never persisted or returned."""

    credential: SecretStr = Field(min_length=1, max_length=16_000, json_schema_extra={"writeOnly": True})
    credential_reference: str = Field(min_length=51, max_length=51)

    @field_validator("credential_reference")
    @classmethod
    def validate_native_reference(cls, value: str) -> str:
        if not re.fullmatch(r"argus-provider-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
            raise ValueError("credential reference must be a native opaque reference")
        return value
