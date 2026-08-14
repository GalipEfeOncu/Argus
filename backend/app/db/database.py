"""SQLite connection and migration entry points for the durable control plane."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from app.config import settings
from app.db.backup import create_pre_migration_backup
from app.db.migrations import MIGRATIONS, apply_migrations


async def get_db() -> aiosqlite.Connection:
    """Open a configured SQLite connection with the safety settings Argus needs."""

    db = await aiosqlite.connect(settings.db_path)
    try:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA busy_timeout = 5000")
        return db
    except BaseException:
        # Cancellation can arrive while connection PRAGMAs are still queued on
        # aiosqlite's worker thread. Drain the connection before its loop exits.
        await db.close()
        raise


@asynccontextmanager
async def transaction(db: aiosqlite.Connection) -> AsyncIterator[None]:
    """Provide an explicit rollback boundary for repository operations."""

    await db.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        await db.rollback()
        raise
    else:
        await db.commit()


async def init_db() -> None:
    """Bring the configured database to the newest known schema version."""

    database_path = Path(settings.db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    await create_pre_migration_backup(database_path, MIGRATIONS)
    db = await get_db()
    try:
        await apply_migrations(db)
    finally:
        await db.close()
