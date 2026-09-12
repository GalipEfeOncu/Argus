"""Add an explicit projectless session kind for direct chats."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    async with db.execute("PRAGMA table_info(sessions)") as cursor:
        columns = {row[1] for row in await cursor.fetchall()}
    if "session_type" not in columns:
        await db.execute("ALTER TABLE sessions ADD COLUMN session_type TEXT NOT NULL DEFAULT 'project'")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_type_updated ON sessions(session_type, updated_at_ms DESC)")
