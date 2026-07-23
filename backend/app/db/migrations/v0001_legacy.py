"""Compatibility baseline for databases created by the original prototype."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            project_path TEXT NOT NULL,
            task TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'setup',
            role_configs TEXT NOT NULL,
            started_at INTEGER NOT NULL,
            completed_at INTEGER,
            token_usage TEXT NOT NULL DEFAULT '{}'
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            agent_role TEXT,
            content TEXT NOT NULL,
            tool_calls TEXT NOT NULL DEFAULT '[]',
            created_at INTEGER NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
