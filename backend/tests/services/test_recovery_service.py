from __future__ import annotations

import json

import pytest

from app.db.database import get_db
from app.db.repositories import EventRepository, SessionRepository
from app.services.recovery_service import RecoveryService


async def _session(database, session_id: str = "recovery-session") -> None:
    await SessionRepository(database).create_legacy_session(
        session_id=session_id, name="Recovery", project_path="workspace", task="Recover", role_configs=[]
    )


@pytest.mark.asyncio
async def test_recovery_rebuilds_projection_and_bounds_snapshots_without_deleting_events(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await _session(database)
        events = EventRepository(database)
        for index, status in enumerate(("preparing", "running", "paused", "running"), start=1):
            await events.append(event_id=f"evt_{index}", session_id="recovery-session", event_type="session.status_changed",
                                actor_id="system", payload={"status": status}, timestamp_ms=index)
            await events.create_snapshot("recovery-session", snapshot_id=f"snapshot_{index}")
        await database.execute("UPDATE sessions SET status = 'failed' WHERE id = 'recovery-session'")
        await database.commit()
        report = await RecoveryService(database).recover_after_restart()
        async with database.execute("SELECT COUNT(*) AS total FROM events WHERE session_id = 'recovery-session'") as cursor:
            event_count = (await cursor.fetchone())["total"]
        async with database.execute("SELECT COUNT(*) AS total FROM event_snapshots WHERE session_id = 'recovery-session'") as cursor:
            snapshot_count = (await cursor.fetchone())["total"]
        async with database.execute("SELECT status FROM sessions WHERE id = 'recovery-session'") as cursor:
            status = (await cursor.fetchone())["status"]
    finally:
        await database.close()

    assert report.sessions == 1
    assert event_count == 4
    assert snapshot_count == 3
    assert status == "running"


@pytest.mark.asyncio
async def test_recovery_marks_lost_mutating_tool_and_provider_operations_unknown_without_replay(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await _session(database)
        events = EventRepository(database)
        await events.append(
            event_id="session-running", session_id="recovery-session", event_type="session.status_changed", actor_id="system",
            payload={"status": "running"}, timestamp_ms=0,
        )
        request = await events.append(
            event_id="tool-request", session_id="recovery-session", event_type="tool.requested", actor_id="builder",
            payload={"toolExecutionId": "tool_1", "assignmentId": "assignment_1", "toolName": "write_file",
                     "operationClass": "mutating", "requestSummary": "Write one isolated file."}, timestamp_ms=1,
        )
        # The test only needs a durable orphan record; disable foreign keys for
        # this focused recovery fixture because full scheduler setup is covered
        # by its own suite.
        await database.execute("PRAGMA foreign_keys = OFF")
        await database.execute(
            """INSERT INTO tool_executions (id, session_id, assignment_id, tool_name, operation_class, request_summary,
               exit_state, artifact_ids_json, requested_event_id, created_at_ms, updated_at_ms)
               VALUES ('tool_1', 'recovery-session', 'assignment_1', 'write_file', 'mutating', 'safe request',
                       'running', '[]', ?, 1, 1)""", (request.event_id,),
        )
        await database.execute(
            """INSERT INTO provider_operations (id, session_id, assignment_id, operation_kind, mutation_class, state,
               request_fingerprint, started_at_ms) VALUES ('provider_1', 'recovery-session', NULL, 'tool_call', 'mutating',
               'running', 'fingerprint', 1)"""
        )
        await database.commit()
        report = await RecoveryService(database).recover_after_restart()
        async with database.execute("SELECT exit_state, result_summary FROM tool_executions WHERE id = 'tool_1'") as cursor:
            tool = await cursor.fetchone()
        async with database.execute("SELECT state FROM provider_operations WHERE id = 'provider_1'") as cursor:
            provider = await cursor.fetchone()
        recovered = await events.list_for_session("recovery-session")
    finally:
        await database.close()

    assert report.unknown_tools == report.unknown_provider_operations == 1
    assert tool["exit_state"] == provider["state"] == "outcome_unknown"
    assert "will not replay" in tool["result_summary"]
    assert [event.event_type for event in recovered].count("tool.completed") == 1
