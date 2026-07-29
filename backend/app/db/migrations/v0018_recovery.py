"""Recovery metadata and indexes for restart-safe orchestration."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    statements = (
        """CREATE TABLE provider_operations (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            assignment_id TEXT REFERENCES assignments(id),
            operation_kind TEXT NOT NULL,
            mutation_class TEXT NOT NULL CHECK (mutation_class IN ('read_only', 'mutating')),
            state TEXT NOT NULL CHECK (state IN ('pending', 'running', 'succeeded', 'failed', 'outcome_unknown')),
            request_fingerprint TEXT NOT NULL,
            result_summary TEXT,
            started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
            completed_at_ms INTEGER
        )""",
        "CREATE INDEX idx_provider_operations_recovery ON provider_operations(state, session_id)",
        "CREATE INDEX idx_tool_executions_recovery ON tool_executions(exit_state, session_id)",
    )
    for statement in statements:
        await db.execute(statement)
