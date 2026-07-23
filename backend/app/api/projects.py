from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.db.database import get_db
from app.schemas.project import ProjectRegisterRequest, ProjectResponse
from app.services.workspace_service import ProjectWorkspaceService, WorkspaceError


router = APIRouter()


def _managed_root() -> Path:
    return Path(settings.db_path).expanduser().resolve().parent / "workspaces"


@router.post("/", response_model=ProjectResponse, status_code=201)
async def register_project(request: ProjectRegisterRequest):
    db = await get_db()
    try:
        return await ProjectWorkspaceService(db, managed_root=_managed_root()).register_project(request.path, request.display_name)
    except WorkspaceError as error:
        raise HTTPException(status_code=422, detail={"code": "unsupported_project", "message": str(error)}) from error
    finally:
        await db.close()


@router.get("/", response_model=list[ProjectResponse])
async def list_projects():
    db = await get_db()
    try:
        return await ProjectWorkspaceService(db, managed_root=_managed_root()).list_projects()
    finally:
        await db.close()
