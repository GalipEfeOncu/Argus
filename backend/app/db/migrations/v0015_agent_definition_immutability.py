"""Make versioned agent definitions append-only and efficient to resolve."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_definitions_role_version "
        "ON agent_definitions(base_role, template_version)"
    )
    for trigger in (
        """CREATE TRIGGER IF NOT EXISTS agent_definitions_are_immutable_update
           BEFORE UPDATE ON agent_definitions
           BEGIN SELECT RAISE(ABORT, 'agent definitions are immutable'); END""",
        """CREATE TRIGGER IF NOT EXISTS agent_definitions_are_immutable_delete
           BEFORE DELETE ON agent_definitions
           BEGIN SELECT RAISE(ABORT, 'agent definitions are immutable'); END""",
    ):
        await db.execute(trigger)
