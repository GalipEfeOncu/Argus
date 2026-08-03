from __future__ import annotations

import json

import aiosqlite
import pytest

from app.db.database import get_db
from app.db.repositories import EventRepository, SessionRepository
from app.services.observability_service import LocalObservability


@pytest.mark.asyncio
async def test_health_reports_runtime_facts_and_redacts_structured_logs(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        service = LocalObservability()
        service.record("INFO", "provider.request", {"apiKey": "sk-abcdefghijklmnop", "prompt": "never export this", "path": "/private/project", "latencyMs": 12})
        service.record("INFO", "provider.api_key.sk-abcdefghijklmnop", {"statusCode": 200})
        await SessionRepository(database).create_legacy_session(session_id="approval-session", name="Approval", project_path="/project", task="diagnostics", role_configs=[])
        requested = await EventRepository(database).append(
            event_id="approval-requested", session_id="approval-session", event_type="approval.requested", actor_id="system",
            payload={"approvalId": "pending-approval", "capability": "workspace.write", "scopeSummary": "workspace"}, timestamp_ms=1,
        )
        await database.execute(
            """INSERT INTO approvals (id, session_id, capability, scope_json, decision, requested_at_ms, request_event_id)
               VALUES ('pending-approval', 'approval-session', 'workspace.write', '{}', 'pending', 1, ?)""", (requested.event_id,)
        )
        await database.commit()
        health = await service.health(database, db_path=str(temporary_sqlite_db))
        logs = service.logs()
    finally:
        await database.close()

    assert health["status"] == "healthy"
    assert health["queues"] == {"runnableAssignments": 0, "activeToolExecutions": 0, "activeProviderOperations": 0, "pendingApprovals": 1, "pendingDecisions": 0, "reservedLimits": 0}
    assert logs[0]["details"] == {"apiKey": "[REDACTED]", "prompt": "[REDACTED]", "path": "[REDACTED]", "latencyMs": 12}
    assert logs[1]["event"] == "runtime.event"
    assert "sk-abcdefghijklmnop" not in json.dumps(logs)


@pytest.mark.asyncio
async def test_support_bundle_contains_only_configuration_shapes_and_event_summaries(temporary_sqlite_db, monkeypatch: pytest.MonkeyPatch) -> None:
    database = await get_db()
    try:
        await SessionRepository(database).create_legacy_session(
            session_id="diagnostic-session", name="Diagnostic", project_path="/private/project", task="raw prompt must not leave the machine", role_configs=[],
        )
        await EventRepository(database).append(
            event_id="diagnostic-event", session_id="diagnostic-session", event_type="message.created", actor_id="human",
            payload={"messageId": "message-1", "authorId": "human", "authorKind": "human", "content": "private user message", "mentionIds": [], "streaming": False}, timestamp_ms=10,
        )
        service = LocalObservability()
        bundle = await service.support_bundle(database, db_path=str(temporary_sqlite_db), session_ids=["diagnostic-session"])
        async def unavailable_summaries(*_args, **_kwargs):
            raise aiosqlite.OperationalError("database is locked")
        monkeypatch.setattr(service, "_session_summaries", unavailable_summaries)
        unavailable_bundle = await service.support_bundle(database, db_path=str(temporary_sqlite_db), session_ids=["diagnostic-session"])
    finally:
        await database.close()

    encoded = json.dumps(bundle)
    summary = bundle["sessions"][0]
    assert summary["eventCounts"] == {"message.created": 1}
    assert summary["configurationShape"] == {}
    assert "private user message" not in encoded
    assert "raw prompt must not leave the machine" not in encoded
    assert "/private/project" not in encoded
    assert any("project file contents" in item for item in bundle["excluded"])
    assert unavailable_bundle["sessions"] == []
    assert unavailable_bundle["logs"][-1]["event"] == "runtime.support_bundle_session_summary_unavailable"


@pytest.mark.asyncio
async def test_corrupt_event_payload_is_visible_as_a_safe_degraded_check(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await SessionRepository(database).create_legacy_session(session_id="corrupt-session", name="Corrupt", project_path="/project", task="diagnostics", role_configs=[])
        await database.execute(
            """INSERT INTO events (id, session_id, sequence, event_type, actor_id, payload_json, timestamp_ms, created_at_ms)
               VALUES ('corrupt-event', 'corrupt-session', 1, 'message.created', 'system', '{', 1, 1)"""
        )
        await database.commit()
        health = await LocalObservability().health(database, db_path=str(temporary_sqlite_db))
    finally:
        await database.close()

    corrupted = next(check for check in health["checks"] if check["code"] == "corrupted_event")
    assert health["status"] == "degraded"
    assert corrupted["action"] is not None
