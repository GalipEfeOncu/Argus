"""Index durable gate evidence by validation and workspace revision."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    await db.execute(
        "CREATE INDEX idx_gate_evidence_current ON gate_evidence(session_id, rule_id, validation_state, invalidated_at_ms)"
    )
