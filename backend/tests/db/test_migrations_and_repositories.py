import asyncio

import aiosqlite
import pytest

from app.db.database import get_db
from app.db.migrations import MIGRATIONS, Migration, apply_migrations
from app.db.repositories import AssignmentAttemptRepository, EventRepository, SessionRepository, UnsafePersistencePayload


REQUIRED_TABLES = {
    "projects", "sessions", "events", "agent_definitions", "session_agents",
    "session_configurations", "skills", "assignments", "assignment_attempts",
    "gate_evidence", "limit_counters", "approvals", "tool_executions",
    "artifacts", "provider_profiles", "command_receipts", "event_snapshots", "schema_migrations",
    "workspaces", "writer_leases", "workspace_audit",
}


async def create_session(database: aiosqlite.Connection, session_id: str = "session_1") -> None:
    await SessionRepository(database).create_legacy_session(
        session_id=session_id,
        name="Test session",
        project_path="workspace",
        task="Verify persistence",
        role_configs=[],
    )


@pytest.mark.asyncio
async def test_fresh_database_has_every_phase_2_1_table_and_migration_metadata(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        async with database.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
            tables = {row["name"] for row in await cursor.fetchall()}
        async with database.execute("SELECT version FROM schema_migrations ORDER BY version") as cursor:
            versions = [row["version"] for row in await cursor.fetchall()]
        async with database.execute("PRAGMA index_list(events)") as cursor:
            event_indexes = {row["name"] for row in await cursor.fetchall()}
    finally:
        await database.close()

    assert REQUIRED_TABLES <= tables
    assert versions == [1, 2, 3, 4, 5, 6, 7, 8]
    assert "idx_events_session_sequence" in event_indexes


@pytest.mark.asyncio
async def test_pre_migration_prototype_database_upgrades_without_losing_session_data(tmp_path) -> None:
    path = tmp_path / "prototype.db"
    async with aiosqlite.connect(path) as database:
        await database.execute("""
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, project_path TEXT NOT NULL,
                task TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'setup', role_configs TEXT NOT NULL,
                started_at REAL NOT NULL, completed_at REAL, token_usage TEXT NOT NULL DEFAULT '{}'
            )
        """)
        await database.execute("""
            INSERT INTO sessions (id, name, project_path, task, status, role_configs, started_at)
            VALUES ('legacy_session', 'Old', 'old-workspace', 'old task', 'setup', '[]', 1)
        """)
        await database.execute("""
            CREATE TABLE messages (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
                agent_role TEXT, content TEXT NOT NULL, tool_calls TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL
            )
        """)
        await database.commit()
        database.row_factory = aiosqlite.Row
        await apply_migrations(database)
        async with database.execute("SELECT task, goal, created_at_ms FROM sessions WHERE id = 'legacy_session'") as cursor:
            row = await cursor.fetchone()

    assert dict(row) == {"task": "old task", "goal": "old task", "created_at_ms": 1000}


@pytest.mark.asyncio
async def test_configuration_version_migration_preserves_rows_and_allows_policy_restoration(tmp_path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "configuration-v7.db"))
    database = await get_db()
    try:
        await apply_migrations(database, MIGRATIONS[:6])
        await create_session(database)
        await database.execute(
            """INSERT INTO session_configurations (id, session_id, version, available_agent_ids_json,
               required_role_rules_json, execution_limits_json, approval_behavior_json, acknowledgements_json,
               policy_hash, created_at_ms)
               VALUES ('config_1', 'session_1', 1, '[]', '[]', '{}', '{}', '[]', 'same_policy', 1)"""
        )
        await database.commit()
        await apply_migrations(database)
        async with database.execute("SELECT id, policy_hash FROM session_configurations") as cursor:
            preserved = await cursor.fetchall()
        await database.execute(
            """INSERT INTO session_configurations (id, session_id, version, available_agent_ids_json,
               required_role_rules_json, execution_limits_json, approval_behavior_json, acknowledgements_json,
               policy_hash, created_at_ms)
               VALUES ('config_2', 'session_1', 2, '[]', '[]', '{}', '{}', '[]', 'same_policy', 2)"""
        )
        with pytest.raises(aiosqlite.IntegrityError, match="session configurations are immutable"):
            await database.execute("UPDATE session_configurations SET policy_hash = 'changed' WHERE id = 'config_1'")
    finally:
        await database.close()

    assert [dict(row) for row in preserved] == [{"id": "config_1", "policy_hash": "same_policy"}]


@pytest.mark.asyncio
async def test_assignment_attempt_context_selection_is_durably_recorded_without_prompt_content(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await database.execute("PRAGMA foreign_keys = OFF")
        await database.execute(
            """INSERT INTO assignment_attempts (id, assignment_id, attempt_number, configuration_version, started_at_ms)
               VALUES ('attempt_1', 'assignment_1', 1, 1, 1)"""
        )
        await database.commit()
        await AssignmentAttemptRepository(database).record_context_selection("attempt_1", {
            "selectedEventIds": ["event_1"],
            "selectedArtifactIds": ["artifact_1"],
            "includedSections": ["goal"],
            "truncatedSections": [],
            "characterCount": 42,
            "selectionFingerprint": "a" * 64,
        })
        async with database.execute(
            "SELECT context_selection_json FROM assignment_attempts WHERE id = 'attempt_1'"
        ) as cursor:
            row = await cursor.fetchone()
    finally:
        await database.close()

    assert row is not None
    assert row["context_selection_json"] == (
        '{"characterCount":42,"includedSections":["goal"],"selectedArtifactIds":["artifact_1"],'
        '"selectedEventIds":["event_1"],"selectionFingerprint":"' + "a" * 64 + '","truncatedSections":[]}'
    )


@pytest.mark.asyncio
async def test_interrupted_migration_rolls_back_schema_and_metadata(tmp_path) -> None:
    async with aiosqlite.connect(tmp_path / "interrupted.db") as database:
        database.row_factory = aiosqlite.Row

        async def fail_after_ddl(db: aiosqlite.Connection) -> None:
            await db.execute("CREATE TABLE interrupted_marker (id TEXT PRIMARY KEY)")
            raise RuntimeError("simulated interruption")

        with pytest.raises(RuntimeError, match="simulated interruption"):
            await apply_migrations(database, (Migration(99, "interrupted", fail_after_ddl),))
        async with database.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'interrupted_marker'"
        ) as cursor:
            assert await cursor.fetchone() is None
        async with database.execute("SELECT COUNT(*) AS total FROM schema_migrations") as cursor:
            assert (await cursor.fetchone())["total"] == 0


@pytest.mark.asyncio
async def test_event_sequence_is_unique_and_transactionally_allocated_under_concurrency(temporary_sqlite_db) -> None:
    setup_database = await get_db()
    try:
        await create_session(setup_database)
    finally:
        await setup_database.close()
    first, second = await asyncio.gather(get_db(), get_db())
    try:
        results = await asyncio.gather(
            EventRepository(first).append(
                event_id="event_1", session_id="session_1", event_type="message.created",
                actor_id="human", payload={"message": "one"}, timestamp_ms=1,
            ),
            EventRepository(second).append(
                event_id="event_2", session_id="session_1", event_type="message.created",
                actor_id="human", payload={"message": "two"}, timestamp_ms=2,
            ),
        )
    finally:
        await first.close()
        await second.close()

    assert sorted(result.sequence for result in results) == [1, 2]


@pytest.mark.asyncio
async def test_event_projection_rebuilds_identically_from_immutable_events(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await create_session(database)
        events = EventRepository(database)
        await events.append(
            event_id="event_created", session_id="session_1", event_type="session.status_changed",
            actor_id="system", payload={"status": "running"}, timestamp_ms=1,
        )
        await events.append(
            event_id="event_paused", session_id="session_1", event_type="session.status_changed",
            actor_id="human", payload={"status": "paused"}, timestamp_ms=2,
        )
        async with database.execute("SELECT status FROM sessions WHERE id = 'session_1'") as cursor:
            stored_projection = (await cursor.fetchone())["status"]
        await database.execute("UPDATE sessions SET status = 'incorrect' WHERE id = 'session_1'")
        await database.commit()
        first_projection = await events.rebuild_session_projection("session_1")
        second_projection = await events.rebuild_session_projection("session_1")
    finally:
        await database.close()

    assert stored_projection == "paused"
    assert first_projection == second_projection == {
        "sessionId": "session_1", "status": "paused", "lastSequence": 2,
    }


@pytest.mark.asyncio
async def test_repository_rejects_private_reasoning_and_recognizable_credentials(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await create_session(database)
        repository = EventRepository(database)
        with pytest.raises(UnsafePersistencePayload):
            await repository.append(
                event_id="event_secret", session_id="session_1", event_type="error.created",
                actor_id="system", payload={"private_reasoning": "hidden"}, timestamp_ms=1,
            )
        with pytest.raises(UnsafePersistencePayload):
            await repository.append(
                event_id="event_credential", session_id="session_1", event_type="error.created",
                actor_id="system", payload={"summary": "ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN"}, timestamp_ms=1,
            )
        with pytest.raises(UnsafePersistencePayload):
            await SessionRepository(database).create_legacy_session(
                session_id="session_secret", name="Secret", project_path="workspace",
                task="Bearer abcdefghijklmnopqrst", role_configs=[],
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_event_rows_are_immutable_and_require_integer_epoch_milliseconds(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await create_session(database)
        events = EventRepository(database)
        await events.append(
            event_id="event_1", session_id="session_1", event_type="message.created",
            actor_id="human", payload={"content": "safe"}, timestamp_ms=1,
        )
        with pytest.raises(aiosqlite.IntegrityError, match="events are immutable"):
            await database.execute("UPDATE events SET event_type = 'changed' WHERE id = 'event_1'")
        with pytest.raises(aiosqlite.IntegrityError, match="events are immutable"):
            await database.execute("DELETE FROM events WHERE id = 'event_1'")
        for invalid_timestamp in (True, 1.5):
            with pytest.raises(ValueError, match="UTC epoch-millisecond"):
                await events.append(
                    event_id=f"event_{invalid_timestamp}", session_id="session_1", event_type="message.created",
                    actor_id="human", payload={"content": "safe"}, timestamp_ms=invalid_timestamp,  # type: ignore[arg-type]
                )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_database_rejects_cross_session_assignment_links_and_duplicate_command_ids(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await create_session(database, "session_1")
        await create_session(database, "session_2")
        events = EventRepository(database)
        await events.append(
            event_id="event_1", session_id="session_1", event_type="message.created", actor_id="human",
            payload={"content": "one"}, timestamp_ms=1, command_id="command_1",
        )
        with pytest.raises(aiosqlite.IntegrityError):
            await events.append(
                event_id="event_duplicate_command", session_id="session_1", event_type="message.created",
                actor_id="human", payload={"content": "duplicate"}, timestamp_ms=2, command_id="command_1",
            )
        await events.append(
            event_id="event_2", session_id="session_2", event_type="message.created", actor_id="human",
            payload={"content": "two"}, timestamp_ms=3,
        )
        await database.execute("""
            INSERT INTO session_agents (id, session_id, role, snapshot_json, created_at_ms)
            VALUES ('agent_2', 'session_2', 'builder', '{}', 1)
        """)
        await database.commit()
        with pytest.raises(aiosqlite.IntegrityError, match="another session"):
            await database.execute("""
                INSERT INTO assignments (
                    id, session_id, assignee_session_agent_id, state, operation_class,
                    acceptance_criteria_json, budget_json, configuration_version, created_event_id,
                    created_at_ms, updated_at_ms
                ) VALUES ('assignment_cross', 'session_1', 'agent_2', 'created', 'read_only', '[]', '{}', 1, 'event_1', 1, 1)
            """)
    finally:
        await database.close()
