"""REST endpoints for the singleton offline local profile."""

from fastapi import APIRouter, HTTPException

from app.db.database import get_db
from app.schemas.local_profile import LocalProfilePatch, LocalProfileResponse, LocalProfileStateResponse
from app.services.local_profile_service import LocalProfileError, LocalProfileService


router = APIRouter()


@router.get("", response_model=LocalProfileStateResponse)
async def get_local_profile() -> LocalProfileStateResponse:
    db = await get_db()
    try:
        return await LocalProfileService(db).get()
    finally:
        await db.close()


@router.patch("", response_model=LocalProfileResponse)
async def patch_local_profile(value: LocalProfilePatch) -> LocalProfileResponse:
    db = await get_db()
    try:
        return await LocalProfileService(db).patch(value)
    except LocalProfileError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "message": error.message}) from error
    finally:
        await db.close()
