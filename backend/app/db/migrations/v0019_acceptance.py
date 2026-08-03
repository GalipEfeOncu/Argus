"""Durable review/acceptance actions and original-project drift baselines."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    await db.execute("ALTER TABLE workspaces ADD COLUMN original_revision_checksum TEXT")
    # Older workspaces did not capture the source project at setup time. Keep
    # their baseline null: review/export remains available, but apply fails
    # closed rather than treating an isolated revision as the original source.
    await db.execute(
        """CREATE TABLE acceptance_actions (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            command_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('apply', 'reject', 'export', 'follow_up')),
            disposition TEXT NOT NULL CHECK (disposition IN ('retain', 'cleanup')),
            state TEXT NOT NULL CHECK (state IN ('pending', 'waiting_approval', 'applying', 'applied', 'rejected', 'exported', 'follow_up_started', 'drifted', 'denied', 'failed', 'outcome_unknown')),
            expected_original_checksum TEXT,
            observed_original_checksum TEXT,
            summary TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            completed_at_ms INTEGER,
            UNIQUE(session_id, command_id)
        )"""
    )
    await db.execute("CREATE INDEX idx_acceptance_actions_recovery ON acceptance_actions(state, session_id)")
