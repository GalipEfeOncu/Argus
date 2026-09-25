"""Record an instruction's delivery attempt across process restarts."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    await db.execute("ALTER TABLE participant_instructions ADD COLUMN delivery_started_at_ms INTEGER")
    await db.execute("ALTER TABLE participant_instructions ADD COLUMN delivery_finished_at_ms INTEGER")
