import json
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from app.schemas.session import SessionCreateRequest, SessionResponse, SessionStatus
from app.db.database import get_db

router = APIRouter()


@router.post("/", response_model=dict)
async def create_session(req: SessionCreateRequest):
    session_id = str(uuid.uuid4())
    name = req.name or f"Session {datetime.now().strftime('%m/%d %H:%M')}"
    now = datetime.now().timestamp()

    async with await get_db() as db:
        await db.execute(
            "INSERT INTO sessions (id, name, project_path, task, status, role_configs, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, name, req.project_path, req.task, "setup",
             json.dumps([rc.model_dump() for rc in req.role_configs]), now)
        )
        await db.commit()

    return {"id": session_id, "name": name}


@router.get("/")
async def list_sessions():
    async with await get_db() as db:
        async with db.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT 50") as cursor:
            rows = await cursor.fetchall()
    return [{"id": r["id"], "name": r["name"], "status": r["status"], "started_at": r["started_at"]} for r in rows]


@router.get("/{session_id}")
async def get_session(session_id: str):
    async with await get_db() as db:
        async with db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cursor:
            row = await cursor.fetchone()
    if not row:
        raise HTTPException(404, "Session not found")
    return dict(row)


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    async with await get_db() as db:
        await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await db.commit()
    return {"deleted": True}
