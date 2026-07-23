import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from app.schemas.session import SessionCreateRequest
from app.db.database import get_db
from app.db.repositories import SessionRepository

router = APIRouter()


@router.post("/", response_model=dict)
async def create_session(req: SessionCreateRequest):
    session_id = str(uuid.uuid4())
    name = req.name or f"Session {datetime.now().strftime('%m/%d %H:%M')}"

    db = await get_db()
    try:
        await SessionRepository(db).create_legacy_session(
            session_id=session_id, name=name, project_path=req.project_path, task=req.task,
            role_configs=[role_config.model_dump() for role_config in req.role_configs],
        )
    finally:
        await db.close()

    return {"id": session_id, "name": name}


@router.get("/")
async def list_sessions():
    db = await get_db()
    try:
        return await SessionRepository(db).list_legacy_sessions()
    finally:
        await db.close()


@router.get("/{session_id}")
async def get_session(session_id: str):
    db = await get_db()
    try:
        row = await SessionRepository(db).get_legacy_session(session_id)
    finally:
        await db.close()
    if not row:
        raise HTTPException(404, "Session not found")
    return dict(row)


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    raise HTTPException(405, "Session deletion requires a future retention-policy workflow")
