from __future__ import annotations

import pytest

from app.api.runtime import idle_status
from app.db.database import get_db
from app.db.repositories import EventRepository, SessionRepository


@pytest.mark.asyncio
async def test_idle_status_keeps_sidecar_running_for_a_pending_approval(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await SessionRepository(database).create_legacy_session(session_id="idle-approval", name="Idle approval", project_path="/project", task="diagnostics", role_configs=[])
        event = await EventRepository(database).append(
            event_id="idle-approval-event", session_id="idle-approval", event_type="approval.requested", actor_id="system",
            payload={"approvalId": "idle-pending", "capability": "workspace.write", "scopeSummary": "workspace"}, timestamp_ms=1,
        )
        await database.execute(
            """INSERT INTO approvals (id, session_id, capability, scope_json, decision, requested_at_ms, request_event_id)
               VALUES ('idle-pending', 'idle-approval', 'workspace.write', '{}', 'pending', 1, ?)""", (event.event_id,)
        )
        await database.commit()
    finally:
        await database.close()

    assert await idle_status() == {"idle": False}
