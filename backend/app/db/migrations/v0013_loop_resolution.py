"""Persist redacted loop signals and one-shot limit-resolution requests."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    statements = (
        """CREATE TABLE loop_signals (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            signal_kind TEXT NOT NULL CHECK (signal_kind IN ('review_finding', 'failure', 'no_progress')),
            fingerprint TEXT NOT NULL,
            occurrence_count INTEGER NOT NULL CHECK (occurrence_count >= 1),
            last_assignment_id TEXT REFERENCES assignments(id),
            last_workspace_checksum TEXT,
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
            UNIQUE(session_id, signal_kind, fingerprint),
            UNIQUE(session_id, fingerprint)
        )""",
        """CREATE TABLE finding_follow_ups (
            session_id TEXT NOT NULL REFERENCES sessions(id),
            finding_fingerprint TEXT NOT NULL,
            assignment_id TEXT NOT NULL REFERENCES assignments(id),
            accepted_at_ms INTEGER NOT NULL CHECK (accepted_at_ms >= 0),
            PRIMARY KEY (session_id, assignment_id),
            FOREIGN KEY (session_id, finding_fingerprint)
                REFERENCES loop_signals(session_id, fingerprint)
        )""",
        """CREATE TABLE limit_resolution_requests (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            source_event_id TEXT NOT NULL REFERENCES events(id),
            assignment_id TEXT REFERENCES assignments(id),
            counter_kind TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            fingerprint TEXT,
            policy_mode TEXT NOT NULL CHECK (policy_mode IN ('ask_user', 'coordinator_decides', 'stop')),
            state TEXT NOT NULL CHECK (state IN ('pending', 'claimed', 'resolved', 'stopped', 'timed_out', 'cancelled')),
            choices_json TEXT NOT NULL,
            decision_id TEXT,
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            resolved_at_ms INTEGER,
            UNIQUE(source_event_id)
        )""",
        "CREATE INDEX idx_loop_signals_session_kind ON loop_signals(session_id, signal_kind, updated_at_ms)",
        "CREATE INDEX idx_finding_follow_ups_session_finding ON finding_follow_ups(session_id, finding_fingerprint)",
        "CREATE INDEX idx_limit_resolution_pending ON limit_resolution_requests(session_id, state, created_at_ms)",
        "CREATE UNIQUE INDEX idx_limit_resolution_one_active ON limit_resolution_requests(session_id) WHERE state IN ('pending', 'claimed')",
        """CREATE TRIGGER finding_follow_ups_same_session_insert
            BEFORE INSERT ON finding_follow_ups
            WHEN (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id
            BEGIN SELECT RAISE(ABORT, 'finding follow-up references another session'); END""",
        """CREATE TRIGGER finding_follow_ups_same_session_update
            BEFORE UPDATE OF session_id, assignment_id ON finding_follow_ups
            WHEN (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id
            BEGIN SELECT RAISE(ABORT, 'finding follow-up references another session'); END""",
        """CREATE TRIGGER loop_signals_same_session_update
            BEFORE UPDATE OF session_id, last_assignment_id ON loop_signals
            WHEN NEW.last_assignment_id IS NOT NULL
              AND (SELECT session_id FROM assignments WHERE id = NEW.last_assignment_id) != NEW.session_id
            BEGIN SELECT RAISE(ABORT, 'loop signal references another session'); END""",
        """CREATE TRIGGER loop_signals_same_session_insert
            BEFORE INSERT ON loop_signals
            WHEN NEW.last_assignment_id IS NOT NULL
              AND (SELECT session_id FROM assignments WHERE id = NEW.last_assignment_id) != NEW.session_id
            BEGIN SELECT RAISE(ABORT, 'loop signal references another session'); END""",
        """CREATE TRIGGER limit_resolution_requests_same_session_insert
            BEFORE INSERT ON limit_resolution_requests
            WHEN (SELECT session_id FROM events WHERE id = NEW.source_event_id) != NEW.session_id
              OR (NEW.assignment_id IS NOT NULL AND (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id)
            BEGIN SELECT RAISE(ABORT, 'limit resolution references another session'); END""",
        """CREATE TRIGGER limit_resolution_requests_same_session_update
            BEFORE UPDATE OF session_id, source_event_id, assignment_id ON limit_resolution_requests
            WHEN (SELECT session_id FROM events WHERE id = NEW.source_event_id) != NEW.session_id
              OR (NEW.assignment_id IS NOT NULL AND (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id)
            BEGIN SELECT RAISE(ABORT, 'limit resolution references another session'); END""",
    )
    for statement in statements:
        await db.execute(statement)
