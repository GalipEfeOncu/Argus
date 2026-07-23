import json

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db, init_db, transaction
from app.db.migrations import MIGRATIONS, apply_migrations
from app.db.repositories import EventRepository, SnapshotChecksumMismatch, _safe_json
from app.main import app
from app.schemas.session_commands import parse_session_command
from app.services.command_processor import CommandProcessor, CommandRejected, event_wire_value
from tests.db.test_migrations_and_repositories import create_session


@pytest.mark.asyncio
async def test_duplicate_command_returns_the_original_correlated_event_after_reconnect(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await create_session(database)
        processor = CommandProcessor(database)
        command = parse_session_command({
            "commandId": "command_message", "type": "message.send",
            "payload": {"content": "A durable message"},
        })
        first = await processor.process("session_1", command)
        second = await processor.process("session_1", command)
        stored = await EventRepository(database).event_for_command("session_1", "command_message")
    finally:
        await database.close()

    assert first.duplicate is False
    assert second.duplicate is True
    assert first.events == second.events == (stored,)
    assert stored is not None and stored.correlation_id == "command_message"
    assert event_wire_value(stored)["payload"]["content"] == "A durable message"


@pytest.mark.asyncio
async def test_lifecycle_transitions_include_waiting_states_and_reject_illegal_commands(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await create_session(database)
        processor = CommandProcessor(database)
        start = parse_session_command({"commandId": "start", "type": "session.start", "payload": {}})
        await processor.process("session_1", start)
        with pytest.raises(CommandRejected, match="illegal_transition:preparing->paused"):
            await processor.process("session_1", parse_session_command({
                "commandId": "bad_pause", "type": "session.pause", "payload": {},
            }))
        await EventRepository(database).append(
            event_id="running", session_id="session_1", event_type="session.status_changed", actor_id="system",
            payload={"status": "running"}, timestamp_ms=1,
        )
        await EventRepository(database).append(
            event_id="waiting_approval", session_id="session_1", event_type="session.status_changed", actor_id="system",
            payload={"status": "waiting_approval"}, timestamp_ms=2,
        )
        approval = await processor.process("session_1", parse_session_command({
            "commandId": "approve", "type": "approval.resolve",
            "payload": {"approvalId": "approval_1", "resolution": "approve"},
        }))
        approval_retry = await processor.process("session_1", parse_session_command({
            "commandId": "approve", "type": "approval.resolve",
            "payload": {"approvalId": "approval_1", "resolution": "approve"},
        }))
        await EventRepository(database).append(
            event_id="waiting_decision", session_id="session_1", event_type="session.status_changed", actor_id="system",
            payload={"status": "waiting_decision"}, timestamp_ms=3,
        )
        partial = await processor.process("session_1", parse_session_command({
            "commandId": "partial", "type": "decision.resolve",
            "payload": {"decisionId": "decision_1", "choice": "deliver_partial"},
        }))
    finally:
        await database.close()

    assert [event.event_type for event in approval.events] == ["approval.resolved", "session.status_changed"]
    assert approval_retry.duplicate is True and approval_retry.events == approval.events
    assert partial.events[-1].payload["status"] == "completed_partial"


@pytest.mark.asyncio
async def test_failed_command_transaction_leaves_no_partial_outcome_for_retry(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await create_session(database)
        processor = CommandProcessor(database)
        invalid = parse_session_command({"commandId": "pause", "type": "session.pause", "payload": {}})
        with pytest.raises(CommandRejected):
            await processor.process("session_1", invalid)
        assert await EventRepository(database).event_for_command("session_1", "pause") is None
        valid = parse_session_command({"commandId": "start", "type": "session.start", "payload": {}})
        outcome = await processor.process("session_1", valid)
    finally:
        await database.close()

    assert outcome.duplicate is False
    assert outcome.events[0].event_type == "session.status_changed"


@pytest.mark.asyncio
async def test_snapshot_checksum_and_replay_match_the_immutable_projection(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await create_session(database)
        events = EventRepository(database)
        for index, status in enumerate(("preparing", "running", "paused")):
            await events.append(
                event_id=f"event_{index}", session_id="session_1", event_type="session.status_changed",
                actor_id="system", payload={"status": status}, timestamp_ms=index,
            )
        snapshot = await events.create_snapshot("session_1", snapshot_id="snapshot_1")
        await events.append(
            event_id="event_after_snapshot", session_id="session_1", event_type="session.status_changed",
            actor_id="system", payload={"status": "running"}, timestamp_ms=4,
        )
        replay = await events.page_after("session_1", after_sequence=snapshot.last_sequence)
        rebuilt = await events.rebuild_session_projection("session_1")
    finally:
        await database.close()

    assert snapshot is not None
    assert snapshot.projection == {"sessionId": "session_1", "status": "paused", "lastSequence": 3}
    assert rebuilt == {"sessionId": "session_1", "status": "running", "lastSequence": 4}
    assert len(snapshot.checksum) == 64
    assert [event.payload["status"] for event in replay.events] == ["running"]


@pytest.mark.asyncio
async def test_tampered_snapshot_is_rejected_by_its_projection_checksum(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await create_session(database)
        events = EventRepository(database)
        await events.append(
            event_id="event_1", session_id="session_1", event_type="session.status_changed", actor_id="system",
            payload={"status": "running"}, timestamp_ms=1,
        )
        snapshot = await events.create_snapshot("session_1")
        assert snapshot is not None
        await database.execute("UPDATE event_snapshots SET projection_json = '{}' WHERE id = ?", (snapshot.id,))
        await database.commit()
        with pytest.raises(SnapshotChecksumMismatch):
            await events.latest_snapshot("session_1")
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_phase_2_1_sequence_zero_rows_upgrade_to_the_canonical_snapshot_cursor(tmp_path, monkeypatch) -> None:
    # A current database would have migrations 1–3, so prove v4 shifts the old
    # zero-based durable stream before the canonical endpoint consumes it.
    from app.config import settings

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "phase-2-1.db"))
    database = await get_db()
    try:
        await apply_migrations(database, MIGRATIONS[:3])
        await create_session(database)
        await database.execute(
            """INSERT INTO events (id, session_id, sequence, event_type, actor_id, correlation_id, command_id,
               payload_json, timestamp_ms, created_at_ms)
               VALUES (?, ?, 0, ?, ?, NULL, NULL, ?, 1, 1)""",
            ("legacy_zero", "session_1", "message.created", "human", json.dumps({"content": "legacy"})),
        )
        await database.commit()
        await apply_migrations(database)
        page = await EventRepository(database).page_after("session_1", after_sequence=0)
    finally:
        await database.close()

    assert [event.sequence for event in page.events] == [1]


def test_canonical_websocket_replays_then_broadcasts_committed_events_to_all_clients(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "canonical-ws.db"
    from app.config import settings

    monkeypatch.setattr(settings, "db_path", str(database_path))

    async def setup() -> None:
        await init_db()
        database = await get_db()
        try:
            await create_session(database)
        finally:
            await database.close()

    import asyncio
    asyncio.run(setup())
    with TestClient(app) as client:
        with client.websocket_connect("/ws/sessions/session_1?after_sequence=0") as first:
            with client.websocket_connect("/ws/sessions/session_1?after_sequence=0") as second:
                assert first.receive_json()["type"] == "session.snapshot"
                assert second.receive_json()["type"] == "session.snapshot"
                first.send_json({
                    "commandId": "broadcast_message", "type": "message.send",
                    "payload": {"content": "Visible to the room"},
                })
                first_event = first.receive_json()
                second_event = second.receive_json()
        timeline = client.get("/sessions/session_1/timeline?after_sequence=0&limit=1")
    assert first_event == second_event
    assert first_event["sequence"] == 1
    assert first_event["correlationId"] == "broadcast_message"
    assert timeline.status_code == 200
    assert timeline.json()["events"] == [first_event]


@pytest.mark.asyncio
async def test_indexed_pages_are_bounded_and_query_plans_use_the_cursor_indexes(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await create_session(database)
        events = EventRepository(database)
        async with transaction(database):
            for index in range(10_000):
                payload = {"content": str(index)}
                await events._append_in_transaction(
                    event_id=f"event_{index}", session_id="session_1", event_type="message.created",
                    actor_id="human", correlation_id=None, command_id=None,
                    payload=payload, payload_json=_safe_json(payload), timestamp_ms=index,
                )
        first = await events.page_after("session_1", after_sequence=-1, limit=200)
        second = await events.page_after("session_1", after_sequence=first.next_after_sequence or -1, limit=200)
        with pytest.raises(ValueError):
            await events.page_after("session_1", after_sequence=-1, limit=201)
        async with database.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM events WHERE session_id = ? AND sequence > ? ORDER BY sequence LIMIT ?",
            ("session_1", 0, 200),
        ) as cursor:
            event_plan = " ".join(str(value) for row in await cursor.fetchall() for value in row)
        async with database.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM artifacts WHERE session_id = ? ORDER BY created_at_ms DESC, id DESC LIMIT ?",
            ("session_1", 50),
        ) as cursor:
            artifact_plan = " ".join(str(value) for row in await cursor.fetchall() for value in row)
    finally:
        await database.close()

    assert len(first.events) == len(second.events) == 200
    assert first.events[0].sequence == 1 and second.events[0].sequence == 201
    assert "idx_events_session_sequence" in event_plan
    assert "idx_artifacts_session_cursor" in artifact_plan
