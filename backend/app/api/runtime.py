"""Local runtime facts used by the native sidecar lifecycle only."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.websocket import connection_hub
from app.db.database import get_db
from app.db.repositories import _now_ms

router = APIRouter(include_in_schema=False)


@router.get("/idle")
async def idle_status() -> dict[str, bool]:
    """Report whether a local sidecar can stop without abandoning work."""

    db = await get_db()
    try:
        now = _now_ms()
        checks = (
            ("SELECT 1 FROM sessions WHERE status IN ('preparing', 'running', 'waiting_approval', 'waiting_decision') LIMIT 1", ()),
            ("SELECT 1 FROM approvals WHERE decision IS NULL LIMIT 1", ()),
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
