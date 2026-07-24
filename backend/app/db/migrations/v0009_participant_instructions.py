"""Persist scheduler-visible human instructions for Coordinator and specialists."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    await db.execute(
        """CREATE TABLE participant_instructions (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            message_event_id TEXT NOT NULL REFERENCES events(id),
            participant_id TEXT NOT NULL,
            delivery_kind TEXT NOT NULL CHECK (delivery_kind IN ('coordinator', 'explicit_mention')),
            state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'superseded', 'delivered')),
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            superseded_at_ms INTEGER,
            UNIQUE(message_event_id, participant_id)
        )"""
    )
    await db.execute(
        """CREATE INDEX idx_participant_instructions_pending
           ON participant_instructions(session_id, participant_id, state, created_at_ms)"""
    )
    for statement in (
        """CREATE TRIGGER participant_instructions_same_session_insert
           BEFORE INSERT ON participant_instructions
           WHEN (SELECT session_id FROM events WHERE id = NEW.message_event_id) != NEW.session_id
           BEGIN SELECT RAISE(ABORT, 'participant instruction references another session'); END""",
        """CREATE TRIGGER participant_instructions_same_session_update
           BEFORE UPDATE OF session_id, message_event_id ON participant_instructions
           WHEN (SELECT session_id FROM events WHERE id = NEW.message_event_id) != NEW.session_id
           BEGIN SELECT RAISE(ABORT, 'participant instruction references another session'); END""",
    ):
        await db.execute(statement)
