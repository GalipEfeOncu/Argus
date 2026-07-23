"""Allow a session to retain released writer-lease audit history."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    # v0005's uniqueness rules made a released lease historical in name only:
    # the same session/holder could never acquire again. Rebuild this small
    # table so active-lease checks remain in the service transaction while all
    # releases stay auditable.
    await db.execute("DROP INDEX IF EXISTS idx_writer_leases_active")
    await db.execute("ALTER TABLE writer_leases RENAME TO writer_leases_v0005")
    await db.execute("""CREATE TABLE writer_leases (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        session_id TEXT NOT NULL REFERENCES sessions(id),
        holder_id TEXT NOT NULL,
        acquired_at_ms INTEGER NOT NULL CHECK (acquired_at_ms >= 0),
        expires_at_ms INTEGER NOT NULL CHECK (expires_at_ms > acquired_at_ms),
        renewed_at_ms INTEGER NOT NULL CHECK (renewed_at_ms >= acquired_at_ms),
        released_at_ms INTEGER,
        release_reason TEXT
    )""")
    await db.execute("""INSERT INTO writer_leases
        (id, project_id, session_id, holder_id, acquired_at_ms, expires_at_ms, renewed_at_ms, released_at_ms, release_reason)
        SELECT id, project_id, session_id, holder_id, acquired_at_ms, expires_at_ms, renewed_at_ms, released_at_ms, release_reason
        FROM writer_leases_v0005""")
    await db.execute("DROP TABLE writer_leases_v0005")
    await db.execute("CREATE INDEX idx_writer_leases_active ON writer_leases(project_id, expires_at_ms) WHERE released_at_ms IS NULL")
