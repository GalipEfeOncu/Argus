"""Permit repeated policy hashes across immutable configuration versions."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    # A user may later restore an earlier policy.  The snapshot version—not the
    # hash—is the unique historical identity, so the old per-session hash
    # uniqueness constraint incorrectly prevented a valid reduction after a
    # permission increase. SQLite requires table recreation to remove it.
    await db.execute("DROP TRIGGER IF EXISTS session_configurations_are_immutable_update")
    await db.execute("DROP TRIGGER IF EXISTS session_configurations_are_immutable_delete")
    await db.execute("ALTER TABLE session_configurations RENAME TO session_configurations_v6")
    await db.execute("""CREATE TABLE session_configurations (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id),
        version INTEGER NOT NULL CHECK (version >= 1),
        available_agent_ids_json TEXT NOT NULL,
        required_role_rules_json TEXT NOT NULL,
        execution_limits_json TEXT NOT NULL,
        approval_behavior_json TEXT NOT NULL,
        acknowledgements_json TEXT NOT NULL DEFAULT '[]',
        policy_hash TEXT NOT NULL,
        created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
        UNIQUE(session_id, version)
    )""")
    await db.execute("""INSERT INTO session_configurations (
        id, session_id, version, available_agent_ids_json, required_role_rules_json,
        execution_limits_json, approval_behavior_json, acknowledgements_json, policy_hash, created_at_ms
    ) SELECT id, session_id, version, available_agent_ids_json, required_role_rules_json,
        execution_limits_json, approval_behavior_json, acknowledgements_json, policy_hash, created_at_ms
    FROM session_configurations_v6""")
    await db.execute("DROP TABLE session_configurations_v6")
    await db.execute("CREATE INDEX idx_session_configurations_session_version ON session_configurations(session_id, version DESC)")
    await db.execute("""CREATE TRIGGER session_configurations_are_immutable_update
        BEFORE UPDATE ON session_configurations
        BEGIN SELECT RAISE(ABORT, 'session configurations are immutable'); END""")
    await db.execute("""CREATE TRIGGER session_configurations_are_immutable_delete
        BEFORE DELETE ON session_configurations
        BEGIN SELECT RAISE(ABORT, 'session configurations are immutable'); END""")
