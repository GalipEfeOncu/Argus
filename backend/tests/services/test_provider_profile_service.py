from __future__ import annotations

import pytest

from app.db.database import get_db
from app.schemas.provider import ManualModelRequest, ProviderProfileCreate
from app.services.provider_profile_service import CredentialLeaseStore, ProviderProfileError, ProviderProfileService


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
