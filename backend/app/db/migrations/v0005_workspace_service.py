"""Durable project workspaces, writer leases, and workspace audit records."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    statements = (
        """CREATE TABLE workspaces (
            session_id TEXT PRIMARY KEY REFERENCES sessions(id),
            project_id TEXT NOT NULL REFERENCES projects(id),
            mode TEXT NOT NULL CHECK (mode IN ('worktree', 'snapshot', 'direct_write')),
            root_path TEXT NOT NULL UNIQUE,
            baseline_path TEXT,
            revision_checksum TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
            cleaned_at_ms INTEGER
        )""",
        """CREATE TABLE writer_leases (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            session_id TEXT NOT NULL REFERENCES sessions(id),
            holder_id TEXT NOT NULL,
            acquired_at_ms INTEGER NOT NULL CHECK (acquired_at_ms >= 0),
            expires_at_ms INTEGER NOT NULL CHECK (expires_at_ms > acquired_at_ms),
            renewed_at_ms INTEGER NOT NULL CHECK (renewed_at_ms >= acquired_at_ms),
            released_at_ms INTEGER,
            release_reason TEXT,
            UNIQUE(project_id, session_id),
            UNIQUE(project_id, holder_id)
        )""",
        """CREATE TABLE workspace_audit (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            action TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
        )""",
        "CREATE INDEX idx_workspaces_project ON workspaces(project_id)",
        "CREATE INDEX idx_writer_leases_active ON writer_leases(project_id, expires_at_ms) WHERE released_at_ms IS NULL",
        "CREATE INDEX idx_workspace_audit_session ON workspace_audit(session_id, created_at_ms DESC)",
    )
    for statement in statements:
        await db.execute(statement)
