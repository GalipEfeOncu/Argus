"""Add precise counter values, durable reservations, and paused-time clocks."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    statements = (
        "ALTER TABLE limit_counters ADD COLUMN consumed_real REAL NOT NULL DEFAULT 0",
        "ALTER TABLE limit_counters ADD COLUMN threshold_real REAL",
        """CREATE TABLE limit_reservations (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            assignment_id TEXT REFERENCES assignments(id),
            counter_kind TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            amount REAL NOT NULL CHECK (amount >= 0),
            state TEXT NOT NULL CHECK (state IN ('reserved', 'consumed', 'released', 'forfeited')),
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            finalized_at_ms INTEGER
        )""",
        """CREATE TABLE session_runtime_clocks (
            session_id TEXT PRIMARY KEY REFERENCES sessions(id),
            accumulated_running_ms INTEGER NOT NULL DEFAULT 0 CHECK (accumulated_running_ms >= 0),
            running_started_at_ms INTEGER,
            updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
        )""",
        "CREATE INDEX idx_limit_reservations_assignment_state ON limit_reservations(assignment_id, state)",
        "CREATE INDEX idx_limit_reservations_scope_state ON limit_reservations(session_id, counter_kind, scope_id, state)",
        """CREATE TRIGGER limit_reservations_same_session_insert
            BEFORE INSERT ON limit_reservations
            WHEN NEW.assignment_id IS NOT NULL
              AND (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id
            BEGIN SELECT RAISE(ABORT, 'limit reservation references another session'); END""",
        """CREATE TRIGGER limit_reservations_same_session_update
            BEFORE UPDATE OF session_id, assignment_id ON limit_reservations
            WHEN NEW.assignment_id IS NOT NULL
              AND (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id
            BEGIN SELECT RAISE(ABORT, 'limit reservation references another session'); END""",
    )
    for statement in statements:
        await db.execute(statement)
    await db.execute("UPDATE limit_counters SET consumed_real = consumed_value, threshold_real = threshold_value")
