"""Add durable scheduler records for proposals, handoffs, and worker attempts."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    statements = (
        """CREATE TABLE assignment_proposals (
            id TEXT NOT NULL,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            parent_assignment_id TEXT REFERENCES assignments(id),
            source_assignment_id TEXT REFERENCES assignments(id),
            actor_id TEXT NOT NULL,
            proposal_json TEXT NOT NULL,
            validation_state TEXT NOT NULL CHECK (validation_state IN ('accepted', 'rejected', 'routed_to_coordinator')),
            validation_code TEXT,
            assignment_id TEXT REFERENCES assignments(id),
            proposed_event_id TEXT NOT NULL REFERENCES events(id),
            resolved_event_id TEXT REFERENCES events(id),
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            PRIMARY KEY (session_id, id)
        )""",
        """CREATE TABLE assignment_handoffs (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            source_assignment_id TEXT NOT NULL REFERENCES assignments(id),
            target_agent_id TEXT,
            summary TEXT NOT NULL,
            artifact_ids_json TEXT NOT NULL DEFAULT '[]',
            follow_up_proposal_json TEXT,
            state TEXT NOT NULL CHECK (state IN ('recorded', 'routed_to_coordinator', 'accepted', 'rejected')),
            event_id TEXT NOT NULL REFERENCES events(id),
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
        )""",
        "ALTER TABLE assignment_attempts ADD COLUMN state TEXT NOT NULL DEFAULT 'running'",
        "ALTER TABLE assignment_attempts ADD COLUMN request_id TEXT",
        "ALTER TABLE assignment_attempts ADD COLUMN updated_at_ms INTEGER NOT NULL DEFAULT 0",
        "CREATE INDEX idx_assignment_proposals_session_state ON assignment_proposals(session_id, validation_state, created_at_ms)",
        "CREATE INDEX idx_assignment_handoffs_session_source ON assignment_handoffs(session_id, source_assignment_id, created_at_ms)",
        "CREATE INDEX idx_assignment_attempts_state ON assignment_attempts(state, started_at_ms)",
    )
    for statement in statements:
        await db.execute(statement)
    # Pre-scheduler rows did not record an attempt state. A completed legacy
    # attempt must never be mistaken for a sidecar-crash orphan after upgrade.
    await db.execute("UPDATE assignment_attempts SET state = 'completed' WHERE completed_at_ms IS NOT NULL")
