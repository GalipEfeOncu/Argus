"""Ordered, transactional SQLite migrations.

Migrations are Python modules so compatibility checks (such as adding a column
to a database created by the pre-migration prototype) stay explicit and tested.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from hashlib import sha256
import inspect
from pathlib import Path
import time

import aiosqlite

from app.db.migrations import (
    v0001_legacy,
    v0002_control_plane,
    v0003_integrity_hardening,
    v0004_event_store,
    v0005_workspace_service,
    v0006_writer_lease_history,
    v0007_configuration_versions,
    v0008_assignment_context_metadata,
)


MigrationFunction = Callable[[aiosqlite.Connection], Awaitable[None]]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: MigrationFunction

    @property
    def checksum(self) -> str:
        source_file = inspect.getsourcefile(self.apply)
        if source_file is None:
            source = inspect.getsource(self.apply).encode()
        else:
            source = Path(source_file).read_bytes()
        return sha256(f"{self.version}:{self.name}:".encode() + source).hexdigest()


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "legacy_session_baseline", v0001_legacy.apply),
    Migration(2, "durable_control_plane", v0002_control_plane.apply),
    Migration(3, "persistence_integrity_hardening", v0003_integrity_hardening.apply),
    Migration(4, "event_store_and_command_receipts", v0004_event_store.apply),
    Migration(5, "project_workspace_service", v0005_workspace_service.apply),
    Migration(6, "writer_lease_history", v0006_writer_lease_history.apply),
    Migration(7, "configuration_versions", v0007_configuration_versions.apply),
    Migration(8, "assignment_context_metadata", v0008_assignment_context_metadata.apply),
)


async def apply_migrations(
    db: aiosqlite.Connection, migrations: Sequence[Migration] = MIGRATIONS
) -> None:
    """Apply unapplied migrations atomically and record immutable metadata."""

    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            checksum TEXT NOT NULL,
            applied_at_ms INTEGER NOT NULL CHECK (applied_at_ms >= 0)
        )
    """)
    await db.commit()

    async with db.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ) as cursor:
        applied = {row["version"]: (row["name"], row["checksum"]) for row in await cursor.fetchall()}

    for migration in migrations:
        known = applied.get(migration.version)
        if known is not None:
            if known != (migration.name, migration.checksum):
                raise RuntimeError(f"Migration metadata mismatch for version {migration.version}")
            continue

        await db.execute("BEGIN IMMEDIATE")
        try:
            await migration.apply(db)
            await db.execute(
                "INSERT INTO schema_migrations (version, name, checksum, applied_at_ms) VALUES (?, ?, ?, ?)",
                (migration.version, migration.name, migration.checksum, int(time.time() * 1000)),
            )
        except BaseException:
            await db.rollback()
            raise
        else:
            await db.commit()
