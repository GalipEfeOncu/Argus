"""Local runtime facts used by the native sidecar lifecycle only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.websocket import connection_hub
from app.db.database import get_db
from app.db.repositories import _now_ms
from app.config import settings
from app.schemas.runtime import RuntimeHealthResponse, SupportBundleResponse
from app.services.observability_service import observability

router = APIRouter()


@router.post("/shutdown", include_in_schema=False, status_code=202)
async def graceful_shutdown(request: Request) -> dict[str, str]:
    """Ask the owning frozen server loop to drain without OS signal semantics."""

    shutdown = getattr(request.app.state, "request_sidecar_shutdown", None)
    if shutdown is None:
        raise HTTPException(503, "Native sidecar shutdown is unavailable.")
    shutdown()
    return {"status": "stopping"}


@router.get("/health", response_model=RuntimeHealthResponse)
async def runtime_health() -> dict[str, object]:
    """Return bounded health facts without project content or provider secrets."""

    db = await get_db()
    try:
        return await observability.health(db, db_path=settings.db_path)
    finally:
        await db.close()


@router.get("/support-bundle", response_model=SupportBundleResponse)
async def support_bundle(session_id: list[str] = Query(default=[])) -> dict[str, object]:
    """Export only redacted local support diagnostics; never project contents."""

    db = await get_db()
    try:
        return await observability.support_bundle(db, db_path=settings.db_path, session_ids=session_id)
    finally:
        await db.close()


@router.get("/idle", include_in_schema=False)
async def idle_status() -> dict[str, bool]:
    """Report whether a local sidecar can stop without abandoning work."""

    db = await get_db()
    try:
        now = _now_ms()
        checks = (
            ("SELECT 1 FROM sessions WHERE status IN ('preparing', 'running', 'waiting_approval', 'waiting_decision') LIMIT 1", ()),
            ("SELECT 1 FROM approvals WHERE decision = 'pending' OR decision IS NULL LIMIT 1", ()),
            ("SELECT 1 FROM tool_executions WHERE exit_state IN ('requested', 'running') LIMIT 1", ()),
            ("SELECT 1 FROM assignment_attempts WHERE state = 'running' LIMIT 1", ()),
            ("SELECT 1 FROM limit_reservations WHERE state = 'reserved' LIMIT 1", ()),
            ("SELECT 1 FROM writer_leases WHERE released_at_ms IS NULL AND expires_at_ms > ? LIMIT 1", (now,)),
            ("SELECT 1 FROM provider_operations WHERE state IN ('pending', 'running') LIMIT 1", ()),
        )
        for query, arguments in checks:
            async with db.execute(query, arguments) as cursor:
                if await cursor.fetchone() is not None:
                    return {"idle": False}
    finally:
        await db.close()
    return {"idle": await connection_hub.connection_count() == 0}
