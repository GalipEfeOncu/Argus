import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from app.schemas.session import SessionCreateRequest
from app.db.database import get_db
from app.db.repositories import EventRepository, SessionRepository
from app.schemas.session_store import ArtifactPageResponse, TimelinePageResponse
from app.services.command_processor import event_wire_value

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


@router.get("/{session_id}/timeline", response_model=TimelinePageResponse)
async def get_timeline_page(
    session_id: str,
    after_sequence: int = Query(default=-1, ge=-1),
    limit: int = Query(default=100, ge=1, le=200),
):
    """Return one indexed timeline page; never hydrate the full event log."""

    db = await get_db()
    try:
        page = await EventRepository(db).page_after(session_id, after_sequence=after_sequence, limit=limit)
    finally:
        await db.close()
    return {
        "events": [event_wire_value(event) for event in page.events],
        "nextAfterSequence": page.next_after_sequence,
    }


@router.get("/{session_id}/artifacts", response_model=ArtifactPageResponse)
async def get_artifact_summaries(
    session_id: str,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
):
    """Return bounded artifact metadata using a stable created-at/id cursor."""

    before: tuple[int, str] | None = None
    if cursor is not None:
        timestamp, separator, artifact_id = cursor.partition(":")
        if not separator or not artifact_id:
            raise HTTPException(422, "Invalid artifact cursor")
        try:
            before = (int(timestamp), artifact_id)
        except ValueError as error:
            raise HTTPException(422, "Invalid artifact cursor") from error
    db = await get_db()
    try:
        page = await EventRepository(db).page_artifact_summaries(session_id, before=before, limit=limit)
    finally:
        await db.close()
    next_cursor = None if page.next_cursor is None else f"{page.next_cursor[0]}:{page.next_cursor[1]}"
    return {"items": list(page.items), "nextCursor": next_cursor}


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    raise HTTPException(405, "Session deletion requires a future retention-policy workflow")
