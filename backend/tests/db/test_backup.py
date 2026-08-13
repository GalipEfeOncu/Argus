from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import os

import aiosqlite
import pytest

from app.db.backup import create_pre_migration_backup, restore_backup
from app.db.migrations import MIGRATIONS, apply_migrations


@pytest.mark.asyncio
async def test_backup_is_created_only_before_pending_migrations(tmp_path: Path) -> None:
    database_path = tmp_path / "argus.db"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE legacy_value (value TEXT NOT NULL)")
    connection.execute("INSERT INTO legacy_value VALUES ('preserved')")
    connection.commit()
    connection.close()

    record = await create_pre_migration_backup(database_path, MIGRATIONS)

    assert record is not None
    if os.name == "posix":
        assert Path(record.backup_path).stat().st_mode & 0o777 == 0o600
    assert json.loads(Path(record.manifest_path).read_text())["sha256"] == record.sha256
    backup = sqlite3.connect(record.backup_path)
    assert backup.execute("SELECT value FROM legacy_value").fetchone() == ("preserved",)
    backup.close()

    database = await aiosqlite.connect(database_path)
    database.row_factory = aiosqlite.Row
    await apply_migrations(database)
    await database.close()
    assert await create_pre_migration_backup(database_path, MIGRATIONS) is None


def test_restore_verifies_checksum_and_retains_displaced_database(tmp_path: Path) -> None:
    backup_path = tmp_path / "backup.db"
    database_path = tmp_path / "argus.db"
    for path, value in ((backup_path, "backup"), (database_path, "current")):
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES (?)", (value,))
        connection.commit()
        connection.close()
    expected = sha256(backup_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="checksum"):
        restore_backup(backup_path, database_path, "0" * 64)

    displaced = restore_backup(backup_path, database_path, expected)
    assert displaced is not None
    restored = sqlite3.connect(database_path)
    assert restored.execute("SELECT value FROM marker").fetchone() == ("backup",)
    restored.close()
    previous = sqlite3.connect(displaced)
    assert previous.execute("SELECT value FROM marker").fetchone() == ("current",)
    previous.close()


def test_restore_rejects_symlink_destination(tmp_path: Path) -> None:
    backup_path = tmp_path / "backup.db"
    real_database = tmp_path / "real.db"
    destination = tmp_path / "argus.db"
    for path in (backup_path, real_database):
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.close()
    destination.symlink_to(real_database)

    with pytest.raises(ValueError, match="symlink"):
        restore_backup(backup_path, destination, sha256(backup_path.read_bytes()).hexdigest())


def test_restore_retires_stale_wal_and_shm_files(tmp_path: Path) -> None:
    backup_path = tmp_path / "backup.db"
    database_path = tmp_path / "argus.db"
    for path in (backup_path, database_path):
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.close()
    for suffix in ("-wal", "-shm"):
        database_path.with_name(database_path.name + suffix).write_text("stale")

    restore_backup(backup_path, database_path, sha256(backup_path.read_bytes()).hexdigest())

    for suffix in ("-wal", "-shm"):
        assert not database_path.with_name(database_path.name + suffix).exists()
        assert list(tmp_path.glob(f"argus.db{suffix}.pre-restore-*"))


def test_restore_rejects_dangling_journal_symlink(tmp_path: Path) -> None:
    backup_path = tmp_path / "backup.db"
    database_path = tmp_path / "argus.db"
    for path in (backup_path, database_path):
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.close()
    database_path.with_name(database_path.name + "-wal").symlink_to(tmp_path / "missing")

    with pytest.raises(ValueError, match="symlink"):
        restore_backup(backup_path, database_path, sha256(backup_path.read_bytes()).hexdigest())
