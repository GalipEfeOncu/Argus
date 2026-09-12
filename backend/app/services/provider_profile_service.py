"""Durable non-secret provider profiles and short-lived credential leases."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hmac
import json
import time
from urllib.parse import urlparse
import uuid

import aiosqlite
import httpx

from app.db.database import transaction
from app.db.repositories import _now_ms, _safe_json
from app.providers.adapters import create_provider
from app.providers.protocol import Provider
from app.providers.registry import (
    ProviderKind,
    ProviderPreset,
    provider_definition,
    resolve_provider_preset,
)
from app.schemas.provider import (
    ManualModelRequest,
    ModelCapability,
    ProviderModelListResponse,
    ProviderProfileCreate,
    ProviderProfileResponse,
)


class ProviderProfileError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


@dataclass(frozen=True)
class ProviderProfile:
    id: str
    provider_kind: ProviderKind
    provider_preset: ProviderPreset
    display_name: str
    endpoint: str | None
    credential_reference: str | None


class CredentialLeaseStore:
    """Process-local credential handoff from the authenticated native bridge.

    Values expire and are intentionally neither serializable nor written to SQLite.
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl_seconds = ttl_seconds
        self._leases: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    async def put(self, profile_id: str, credential: str) -> None:
        async with self._lock:
            self._leases[profile_id] = (credential, time.monotonic() + self._ttl_seconds)

    async def get(self, profile_id: str) -> str | None:
        async with self._lock:
            lease = self._leases.get(profile_id)
            if lease is None or lease[1] <= time.monotonic():
                self._leases.pop(profile_id, None)
                return None
            return lease[0]

    async def revoke(self, profile_id: str) -> None:
        async with self._lock:
            self._leases.pop(profile_id, None)


credential_leases = CredentialLeaseStore()


class ProviderProfileService:
    def __init__(self, db: aiosqlite.Connection, *, leases: CredentialLeaseStore = credential_leases) -> None:
        self._db, self._leases = db, leases

    async def list(self) -> list[ProviderProfileResponse]:
        async with self._db.execute("SELECT * FROM provider_profiles ORDER BY display_name, created_at_ms") as cursor:
            return [self._response(row) for row in await cursor.fetchall()]

    async def create(self, value: ProviderProfileCreate) -> ProviderProfileResponse:
        definition = resolve_provider_preset(value.provider_preset, value.provider_kind, value.endpoint)
        if definition.provider_kind != value.provider_kind:
            raise ProviderProfileError("provider_preset_mismatch", "The provider preset does not match its adapter kind.")
        profile_id, now = f"prv_{uuid.uuid4().hex}", _now_ms()
        endpoint = value.endpoint or definition.default_endpoint
        async with transaction(self._db):
            await self._db.execute(
                """INSERT INTO provider_profiles (id, provider_kind, display_name, endpoint, credential_reference, metadata_json, created_at_ms, updated_at_ms)
                   VALUES (?, ?, ?, ?, ?, '{}', ?, ?)""",
                (profile_id, definition.provider_kind, value.display_name, endpoint, value.credential_reference, now, now),
            )
            await self._db.execute(
                "UPDATE provider_profiles SET metadata_json = ? WHERE id = ?",
                (_safe_json({"providerPreset": definition.preset}), profile_id),
            )
        return ProviderProfileResponse(
            id=profile_id,
            provider_kind=definition.provider_kind,
            provider_preset=definition.preset,
            display_name=value.display_name,
            endpoint=endpoint,
            credential_configured=value.credential_reference is not None,
            credential_required=definition.credential_required,
            created_at_ms=now,
            updated_at_ms=now,
        )

    async def delete(self, profile_id: str) -> None:
        async with transaction(self._db):
            cursor = await self._db.execute("DELETE FROM provider_profiles WHERE id = ?", (profile_id,))
            if cursor.rowcount != 1:
                raise ProviderProfileError("provider_not_found", "Provider profile was not found.")
        await self._leases.revoke(profile_id)

    async def get(self, profile_id: str) -> ProviderProfile:
        async with self._db.execute("SELECT * FROM provider_profiles WHERE id = ?", (profile_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise ProviderProfileError("provider_not_found", "Provider profile was not found.")
        return self._profile(row)

    async def lease_credential(self, profile_id: str, credential_reference: str, credential: str) -> None:
        profile = await self.get(profile_id)
        if profile.credential_reference is None or not hmac.compare_digest(profile.credential_reference, credential_reference):
            raise ProviderProfileError("credential_not_configured", "This provider does not have a credential reference.")
        await self._leases.put(profile_id, credential)

    async def runtime_provider(self, profile_id: str, model_id: str) -> Provider:
        profile = await self.get(profile_id)
        credential = await self._leases.get(profile_id)
        if credential is None and profile.credential_reference is not None:
            raise ProviderProfileError("credential_unavailable", "Credential access is unavailable; reconnect the native credential store.")
        api_key = credential or ("ollama" if profile.provider_preset == "ollama" else "")
        return create_provider(profile.provider_kind, model_id=model_id, api_key=api_key, base_url=profile.endpoint)

    async def models(self, profile_id: str, manual: ManualModelRequest | None = None) -> ProviderModelListResponse:
        profile = await self.get(profile_id)
        if manual is not None:
            return ProviderModelListResponse(models=[ModelCapability(id=manual.model_id, display_name=manual.model_id, source="manual")], discovery_status="available")
        credential = await self._leases.get(profile_id)
        if profile.credential_reference is not None and credential is None:
            return ProviderModelListResponse(models=[], discovery_status="credential_required")
        try:
            models = await self._discover_profile_models(profile, credential or "")
            return ProviderModelListResponse(models=models, discovery_status="available")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            fallback = self._fallback_models(profile.provider_preset)
            if fallback:
                return ProviderModelListResponse(models=fallback, discovery_status="available")
            return ProviderModelListResponse(models=[], discovery_status="unavailable", error="Model discovery is temporarily unavailable.")

    async def _discover_profile_models(self, profile: ProviderProfile, credential: str) -> list[ModelCapability]:
        if profile.provider_preset == "google":
            return await self._discover_google(profile.endpoint, credential)
        if profile.provider_preset == "anthropic":
            return await self._discover_anthropic(profile.endpoint, credential)
        endpoint = profile.endpoint or provider_definition(profile.provider_preset).default_endpoint
        if profile.provider_preset == "openai" and endpoint is None:
            endpoint = "https://api.openai.com/v1"
        if endpoint is None:
            raise ValueError("Model discovery requires an endpoint.")
        return await self._discover_openai_compat(endpoint, credential)

    async def _discover_openai_compat(self, endpoint: str, credential: str) -> list[ModelCapability]:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("invalid endpoint")
        url = f"{endpoint.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {credential}"} if credential else {}
        timeout = httpx.Timeout(10.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        raw = payload.get("data", []) if isinstance(payload, dict) else []
        return self._openai_model_capabilities(raw)

    async def _discover_anthropic(self, endpoint: str | None, credential: str) -> list[ModelCapability]:
        base = endpoint or "https://api.anthropic.com"
        normalized_base = base.rstrip('/')
        url = f"{normalized_base}{'/models' if normalized_base.endswith('/v1') else '/v1/models'}"
        headers = {"x-api-key": credential, "anthropic-version": "2023-06-01"}
        timeout = httpx.Timeout(10.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        raw = payload.get("data", []) if isinstance(payload, dict) else []
        models: list[ModelCapability] = []
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            models.append(ModelCapability(
                id=item["id"],
                display_name=str(item.get("display_name") or item["id"]),
                context_window=_positive_int(item.get("max_input_tokens")),
                supports_tools=True,
                supports_chat=True,
                source="discovered",
            ))
        return _unique_models(models)

    async def _discover_google(self, endpoint: str | None, credential: str) -> list[ModelCapability]:
        base = endpoint or "https://generativelanguage.googleapis.com/v1beta"
        url = f"{base.rstrip('/')}/models"
        headers = {"x-goog-api-key": credential}
        timeout = httpx.Timeout(10.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.get(url, headers=headers, params={"pageSize": "1000"})
            response.raise_for_status()
            payload = response.json()
        raw = payload.get("models", []) if isinstance(payload, dict) else []
        models: list[ModelCapability] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("baseModelId") or str(item.get("name", "")).removeprefix("models/")
            if not name:
                continue
            actions = item.get("supportedGenerationMethods", [])
            supports_chat = "generateContent" in actions if isinstance(actions, list) else None
            models.append(ModelCapability(
                id=name,
                display_name=str(item.get("displayName") or name),
                context_window=_positive_int(item.get("inputTokenLimit")),
                supports_tools=None,
                supports_structured_output=None,
                supports_chat=supports_chat,
                source="discovered",
            ))
        return _unique_models(models)

    @staticmethod
    def _fallback_models(preset: ProviderPreset) -> list[ModelCapability]:
        definition = provider_definition(preset)
        return [ModelCapability(
            id=model_id,
            display_name=model_id,
            supports_tools=True,
            supports_structured_output=True,
            supports_chat=True,
            source="catalog",
        ) for model_id in definition.fallback_model_ids]

    @staticmethod
    def _response(row: aiosqlite.Row) -> ProviderProfileResponse:
        profile = ProviderProfileService._profile(row)
        definition = provider_definition(profile.provider_preset)
        return ProviderProfileResponse(
            id=profile.id,
            provider_kind=profile.provider_kind,
            provider_preset=profile.provider_preset,
            display_name=profile.display_name,
            endpoint=profile.endpoint,
            credential_configured=profile.credential_reference is not None,
            credential_required=definition.credential_required,
            created_at_ms=row["created_at_ms"],
            updated_at_ms=row["updated_at_ms"],
        )

    @staticmethod
    def _profile(row: aiosqlite.Row) -> ProviderProfile:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        preset = metadata.get("providerPreset") if isinstance(metadata, dict) else None
        definition = resolve_provider_preset(preset, row["provider_kind"], row["endpoint"])
        endpoint = row["endpoint"] or definition.default_endpoint
        return ProviderProfile(str(row["id"]), definition.provider_kind, definition.preset, row["display_name"], endpoint, row["credential_reference"])

    @staticmethod
    def _openai_model_capabilities(raw: object) -> list[ModelCapability]:
        if not isinstance(raw, list):
            raise ValueError("provider model response is invalid")
        models: list[ModelCapability] = []
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            model_id = item["id"]
            supported_parameters = item.get("supported_parameters")
            supports_tools = "tools" in supported_parameters if isinstance(supported_parameters, list) else None
            models.append(ModelCapability(
                id=model_id,
                display_name=str(item.get("display_name") or model_id),
                context_window=_positive_int(item.get("context_length") or item.get("context_window")),
                supports_tools=supports_tools,
                supports_structured_output=None,
                supports_chat=_supports_chat_model(model_id),
                source="discovered",
            ))
        return _unique_models(models)


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _supports_chat_model(model_id: str) -> bool:
    normalized = model_id.lower()
    non_chat_markers = ("embedding", "whisper", "moderation", "dall-e", "gpt-image", "tts", "transcrib", "rerank")
    return not any(marker in normalized for marker in non_chat_markers)


def _unique_models(models: list[ModelCapability]) -> list[ModelCapability]:
    unique: dict[str, ModelCapability] = {}
    for model in models:
        unique.setdefault(model.id, model)
    return list(unique.values())[:2_000]
