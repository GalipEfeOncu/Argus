from __future__ import annotations

import pytest

from app.db.database import get_db
from app.providers.registry import PROVIDER_DEFINITIONS
from app.schemas.provider import ManualModelRequest, ProviderProfileCreate
from app.services.provider_profile_service import CredentialLeaseStore, ProviderProfileError, ProviderProfileService


def test_provider_registry_contains_the_supported_presets() -> None:
    assert [definition.preset for definition in PROVIDER_DEFINITIONS] == [
        "openai", "anthropic", "google", "openrouter", "deepseek", "kimi",
        "xai", "mistral", "groq", "ollama", "custom",
    ]


def test_openai_model_capabilities_exclude_extraction_models_from_chat_and_prefer_free_models() -> None:
    models = ProviderProfileService._openai_model_capabilities([
        {
            "id": "inference-net/schematron-v2-turbo",
            "name": "Inference.net: Schematron V2 Turbo",
            "description": "An HTML-to-JSON extraction model.",
            "pricing": {"prompt": "0.00000003", "completion": "0.00000015"},
        },
        {
            "id": "paid/chat-model",
            "name": "Paid Chat Model",
            "description": "A general-purpose text model.",
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        },
        {
            "id": "free/chat-model:free",
            "name": "Free Chat Model",
            "description": "A general-purpose text model.",
            "pricing": {"prompt": "0", "completion": "0"},
        },
    ])

    assert [model.id for model in models] == ["free/chat-model:free", "paid/chat-model", "inference-net/schematron-v2-turbo"]
    assert models[0].display_name == "Free Chat Model"
    assert models[-1].supports_chat is False


@pytest.mark.asyncio
async def test_provider_profile_persists_only_an_opaque_credential_reference(temporary_sqlite_db) -> None:
    db = await get_db()
    try:
        service = ProviderProfileService(db, leases=CredentialLeaseStore())
        profile = await service.create(ProviderProfileCreate(
            provider_kind="openai", display_name="OpenAI", credential_reference="argus-provider-00000000-0000-4000-8000-000000000001",
        ))
        await service.lease_credential(profile.id, "argus-provider-00000000-0000-4000-8000-000000000001", "super-secret-value")
        async with db.execute("SELECT credential_reference, metadata_json FROM provider_profiles WHERE id = ?", (profile.id,)) as cursor:
            stored = await cursor.fetchone()
    finally:
        await db.close()

    assert stored["credential_reference"] == "argus-provider-00000000-0000-4000-8000-000000000001"
    assert "super-secret-value" not in stored["metadata_json"]
    assert profile.credential_configured is True


@pytest.mark.asyncio
async def test_provider_model_catalog_manual_model_and_missing_credential_are_normalized(temporary_sqlite_db) -> None:
    db = await get_db()
    try:
        service = ProviderProfileService(db, leases=CredentialLeaseStore())
        profile = await service.create(ProviderProfileCreate(
            provider_kind="anthropic", display_name="Anthropic", credential_reference="argus-provider-00000000-0000-4000-8000-000000000002",
        ))
        missing = await service.models(profile.id)
        manual = await service.models(profile.id, ManualModelRequest(model_id="my-explicit-model"))
        await service.lease_credential(profile.id, "argus-provider-00000000-0000-4000-8000-000000000002", "not-persisted")
        catalog = await service.models(profile.id)
    finally:
        await db.close()

    assert missing.discovery_status == "credential_required"
    assert manual.models[0].source == "manual"
    assert catalog.models[0].supports_tools is True


@pytest.mark.asyncio
async def test_openai_model_discovery_uses_the_native_models_endpoint(temporary_sqlite_db, monkeypatch: pytest.MonkeyPatch) -> None:
    db = await get_db()
    try:
        service = ProviderProfileService(db, leases=CredentialLeaseStore())
        profile = await service.create(ProviderProfileCreate(
            provider_kind="openai", display_name="OpenAI", credential_reference="argus-provider-00000000-0000-4000-8000-000000000005",
        ))
        calls: list[tuple[str, str]] = []

        async def discover(endpoint: str, credential: str):
            calls.append((endpoint, credential))
            return []

        monkeypatch.setattr(service, "_discover_openai_compat", discover)
        await service.lease_credential(profile.id, "argus-provider-00000000-0000-4000-8000-000000000005", "not-persisted")
        result = await service.models(profile.id)
    finally:
        await db.close()

    assert result.discovery_status == "available"
    assert calls == [("https://api.openai.com/v1", "not-persisted")]


@pytest.mark.asyncio
async def test_ollama_preset_is_local_and_does_not_require_a_credential(temporary_sqlite_db) -> None:
    db = await get_db()
    try:
        service = ProviderProfileService(db, leases=CredentialLeaseStore())
        profile = await service.create(ProviderProfileCreate(
            provider_kind="openai_compat", provider_preset="ollama", display_name="Local Ollama",
        ))
    finally:
        await db.close()

    assert profile.provider_preset == "ollama"
    assert profile.endpoint == "http://localhost:11434/v1"
    assert profile.credential_required is False


@pytest.mark.asyncio
async def test_provider_profile_rejects_runtime_resolution_without_short_lived_lease(temporary_sqlite_db) -> None:
    db = await get_db()
    try:
        service = ProviderProfileService(db, leases=CredentialLeaseStore())
        profile = await service.create(ProviderProfileCreate(
            provider_kind="google", display_name="Google", credential_reference="argus-provider-00000000-0000-4000-8000-000000000003",
        ))
        with pytest.raises(ProviderProfileError, match="Credential access") as error:
            await service.runtime_provider(profile.id, "gemini-2.5-flash")
    finally:
        await db.close()

    assert error.value.code == "credential_unavailable"


def test_provider_profile_rejects_secret_like_credential_reference() -> None:
    with pytest.raises(ValueError, match="native opaque"):
        ProviderProfileCreate(provider_kind="openai", display_name="OpenAI", credential_reference="sk-real-secret")


@pytest.mark.asyncio
async def test_credential_lease_requires_the_profile_owned_reference(temporary_sqlite_db) -> None:
    db = await get_db()
    try:
        service = ProviderProfileService(db, leases=CredentialLeaseStore())
        profile = await service.create(ProviderProfileCreate(provider_kind="openai", display_name="OpenAI", credential_reference="argus-provider-00000000-0000-4000-8000-000000000004"))
        with pytest.raises(ProviderProfileError) as error:
            await service.lease_credential(profile.id, "argus-provider-00000000-0000-4000-8000-000000000005", "not-persisted")
    finally:
        await db.close()

    assert error.value.code == "credential_not_configured"
