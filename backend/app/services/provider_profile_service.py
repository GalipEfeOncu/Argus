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
from app.providers.adapters import ProviderKind, create_provider
from app.providers.protocol import Provider
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


_CATALOG: dict[ProviderKind, tuple[ModelCapability, ...]] = {
    "openai": (ModelCapability(id="gpt-4o-mini", display_name="GPT-4o mini", context_window=128000, supports_tools=True, supports_structured_output=True, source="catalog"),),
    "anthropic": (ModelCapability(id="claude-sonnet-4-20250514", display_name="Claude Sonnet 4", context_window=200000, supports_tools=True, supports_structured_output=True, source="catalog"),),
    "google": (ModelCapability(id="gemini-2.5-flash", display_name="Gemini 2.5 Flash", context_window=1000000, supports_tools=True, supports_structured_output=True, source="catalog"),),
    "openai_compat": (),
}


class ProviderProfileService:
    def __init__(self, db: aiosqlite.Connection, *, leases: CredentialLeaseStore = credential_leases) -> None:
        self._db, self._leases = db, leases

    async def list(self) -> list[ProviderProfileResponse]:
        async with self._db.execute("SELECT * FROM provider_profiles ORDER BY display_name, created_at_ms") as cursor:
            return [self._response(row) for row in await cursor.fetchall()]

    async def create(self, value: ProviderProfileCreate) -> ProviderProfileResponse:
        profile_id, now = f"prv_{uuid.uuid4().hex}", _now_ms()
        async with transaction(self._db):
            await self._db.execute(
                """INSERT INTO provider_profiles (id, provider_kind, display_name, endpoint, credential_reference, metadata_json, created_at_ms, updated_at_ms)
                   VALUES (?, ?, ?, ?, ?, '{}', ?, ?)""",
                (profile_id, value.provider_kind, value.display_name, value.endpoint, value.credential_reference, now, now),
            )
        return ProviderProfileResponse(id=profile_id, provider_kind=value.provider_kind, display_name=value.display_name, endpoint=value.endpoint, credential_configured=value.credential_reference is not None, created_at_ms=now, updated_at_ms=now)

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
        return ProviderProfile(str(row["id"]), row["provider_kind"], row["display_name"], row["endpoint"], row["credential_reference"])

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
        return create_provider(profile.provider_kind, model_id=model_id, api_key=credential or "", base_url=profile.endpoint)

    async def models(self, profile_id: str, manual: ManualModelRequest | None = None) -> ProviderModelListResponse:
        profile = await self.get(profile_id)
        if manual is not None:
            return ProviderModelListResponse(models=[ModelCapability(id=manual.model_id, display_name=manual.model_id, source="manual")], discovery_status="available")
        credential = await self._leases.get(profile_id)
        if profile.credential_reference is not None and credential is None:
            return ProviderModelListResponse(models=[], discovery_status="credential_required")
        if profile.provider_kind != "openai_compat":
            return ProviderModelListResponse(models=list(_CATALOG[profile.provider_kind]), discovery_status="available")
        if profile.endpoint is None:
            return ProviderModelListResponse(models=[], discovery_status="unavailable", error="Model discovery requires an endpoint.")
        try:
            return ProviderModelListResponse(models=await self._discover_openai_compat(profile.endpoint, credential or ""), discovery_status="available")
        except (httpx.HTTPError, ValueError):
            return ProviderModelListResponse(models=[], discovery_status="unavailable", error="Model discovery is temporarily unavailable.")

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
        return [ModelCapability(id=item["id"], display_name=item["id"], source="discovered") for item in raw if isinstance(item, dict) and isinstance(item.get("id"), str)][:200]

    @staticmethod
    def _response(row: aiosqlite.Row) -> ProviderProfileResponse:
        return ProviderProfileResponse(id=row["id"], provider_kind=row["provider_kind"], display_name=row["display_name"], endpoint=row["endpoint"], credential_configured=row["credential_reference"] is not None, created_at_ms=row["created_at_ms"], updated_at_ms=row["updated_at_ms"])
