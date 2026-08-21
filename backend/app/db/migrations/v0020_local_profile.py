"""Singleton non-secret profile for the current local desktop user."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE local_profile (
            id TEXT PRIMARY KEY CHECK (id = 'local'),
            display_name TEXT NOT NULL
                CHECK (length(display_name) BETWEEN 1 AND 80)
                CHECK (display_name = trim(display_name)),
            bio TEXT
                CHECK (bio IS NULL OR length(bio) <= 280)
                CHECK (bio IS NULL OR bio = trim(bio)),
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms)
        )
    """)
