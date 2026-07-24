"""Persist safe assignment-context selection metadata separately from checkpoints."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    await db.execute(
        "ALTER TABLE assignment_attempts ADD COLUMN context_selection_json TEXT NOT NULL DEFAULT '{}'"
    )
