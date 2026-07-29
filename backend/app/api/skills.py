"""Local skill package import, review, and explicit enablement endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.db.database import get_db
from app.schemas.skill import SkillEnableRequest, SkillImportRequest, SkillPackageResponse
from app.services.session_configuration_service import ConfigurationError
from app.services.skill_package_service import SkillPackageService


router = APIRouter()


@router.get("/", response_model=list[SkillPackageResponse])
async def list_skills() -> list[SkillPackageResponse]:
    db = await get_db()
    try:
        return await SkillPackageService(db).list()
    finally:
        await db.close()


@router.post("/import", response_model=SkillPackageResponse, status_code=status.HTTP_201_CREATED)
async def import_skill(request: SkillImportRequest) -> SkillPackageResponse:
    db = await get_db()
    try:
        return await SkillPackageService(db).import_package(request)
    except ConfigurationError as error:
        raise HTTPException(422, {"code": error.code, "message": str(error)}) from error
    finally:
        await db.close()


@router.post("/{skill_id}/enable", response_model=SkillPackageResponse)
async def enable_skill(skill_id: str, request: SkillEnableRequest) -> SkillPackageResponse:
    db = await get_db()
    try:
        return await SkillPackageService(db).set_enabled(skill_id, request.enabled)
    except ConfigurationError as error:
        raise HTTPException(404 if error.code == "skill_not_found" else 422, {"code": error.code, "message": str(error)}) from error
    finally:
        await db.close()
