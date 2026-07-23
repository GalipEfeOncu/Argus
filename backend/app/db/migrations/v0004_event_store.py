"""Event-store read models and durable command receipts for Phase 2.2."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    # Phase 2.1 allocated its first durable event at zero while the canonical
    # snapshot transport reserves zero as its initial cursor. Shift existing
    # rows without transient uniqueness collisions before exposing replay.
    # The v0003 immutability trigger protects normal runtime writes; temporarily
    # replace it inside this migration's rollback boundary to repair the cursor.
    await db.execute("DROP TRIGGER IF EXISTS events_are_immutable_update")
    await db.execute("UPDATE events SET sequence = sequence + 1000000000")
    await db.execute("UPDATE events SET sequence = sequence - 999999999")
    await db.execute("""CREATE TRIGGER events_are_immutable_update
        BEFORE UPDATE ON events
        BEGIN SELECT RAISE(ABORT, 'events are immutable'); END""")
    statements = (
        """CREATE TABLE command_receipts (
            session_id TEXT NOT NULL REFERENCES sessions(id),
            command_id TEXT NOT NULL,
            command_type TEXT NOT NULL,
            command_json TEXT NOT NULL,
            outcome_event_id TEXT NOT NULL REFERENCES events(id),
            outcome_event_ids_json TEXT NOT NULL DEFAULT '[]',
            accepted_at_ms INTEGER NOT NULL CHECK (accepted_at_ms >= 0),
            PRIMARY KEY (session_id, command_id)
        )""",
        """CREATE TABLE event_snapshots (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            last_sequence INTEGER NOT NULL CHECK (last_sequence >= 0),
            projection_json TEXT NOT NULL,
            projection_checksum TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            UNIQUE(session_id, last_sequence),
            UNIQUE(session_id, projection_checksum)
        )""",
        "CREATE INDEX idx_command_receipts_session_accepted ON command_receipts(session_id, accepted_at_ms DESC)",
        "CREATE INDEX idx_snapshots_session_sequence ON event_snapshots(session_id, last_sequence DESC)",
        "CREATE INDEX idx_artifacts_session_cursor ON artifacts(session_id, created_at_ms DESC, id DESC)",
    )
    for statement in statements:
        await db.execute(statement)
