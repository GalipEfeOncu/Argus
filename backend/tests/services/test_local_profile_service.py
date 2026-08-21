import pytest

from app.db.database import get_db
from app.schemas.local_profile import LocalProfilePatch
from app.services.local_profile_service import LocalProfileError, LocalProfileService


@pytest.mark.asyncio
async def test_local_profile_create_partial_update_clear_and_noop(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        service = LocalProfileService(database)
        assert (await service.get()).profile is None

        with pytest.raises(LocalProfileError) as missing_name:
            await service.patch(LocalProfilePatch.model_validate({"bio": "Local only"}))
        assert missing_name.value.code == "display_name_required"
        assert (await service.get()).profile is None

        created = await service.patch(LocalProfilePatch.model_validate({"displayName": "Ada", "bio": "Local only"}))
        no_op = await service.patch(LocalProfilePatch.model_validate({"displayName": "Ada"}))
        updated = await service.patch(LocalProfilePatch.model_validate({"bio": None}))
    finally:
        await database.close()

    assert created.display_name == "Ada" and created.bio == "Local only"
    assert no_op.updated_at_ms == created.updated_at_ms
    assert updated.display_name == "Ada" and updated.bio is None
    assert updated.updated_at_ms > created.updated_at_ms
