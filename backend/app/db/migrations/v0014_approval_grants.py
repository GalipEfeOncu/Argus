"""Harden approval records into scoped, revocable policy-bound grants."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    for definition in (
        "grant_scope TEXT NOT NULL DEFAULT 'once' CHECK (grant_scope IN ('once', 'scope', 'session'))",
        "scope_path TEXT NOT NULL DEFAULT '.'",
        "policy_hash TEXT",
        "revoked_at_ms INTEGER",
        "consumed_at_ms INTEGER",
        "operation_class TEXT NOT NULL DEFAULT 'read_only' CHECK (operation_class IN ('read_only', 'mutating'))",
    ):
        await db.execute(f"ALTER TABLE approvals ADD COLUMN {definition}")
    await db.execute("CREATE INDEX idx_approvals_active_grant ON approvals(session_id, capability, policy_hash, grant_expires_at_ms)")
