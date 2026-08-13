"""Fail-closed SQLite backup and recovery helpers for schema migrations."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Sequence

from app.db.migrations import Migration


@dataclass(frozen=True)
class BackupRecord:
    database_path: str
    backup_path: str
    manifest_path: str
    sha256: str
    bytes: int
    from_version: int
    to_version: int
    created_at_ms: int


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _applied_versions(connection: sqlite3.Connection) -> set[int]:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if table is None:
        return set()
    return {int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")}


def _has_user_data(connection: sqlite3.Connection) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
    ).fetchone() is not None


def _create_backup(database_path: Path, migrations: Sequence[Migration]) -> BackupRecord | None:
    if database_path.is_symlink():
        raise RuntimeError("Database path must not be a symlink during migration")
    if not database_path.is_file() or database_path.stat().st_size == 0:
        return None

    source = sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        integrity = source.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise RuntimeError("Database integrity check failed; migrations were not started")
        if not _has_user_data(source):
            return None

        applied = _applied_versions(source)
        pending = [migration.version for migration in migrations if migration.version not in applied]
        if not pending:
            return None

        from_version = max(applied, default=0)
        to_version = max(migration.version for migration in migrations)
        created_at_ms = time.time_ns() // 1_000_000
        backup_dir = database_path.parent / "backups"
        if backup_dir.is_symlink():
            raise RuntimeError("Migration backup directory must not be a symlink")
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        stem = f"{database_path.stem}-pre-migration-v{from_version}-to-v{to_version}-{time.time_ns()}"
        backup_path = backup_dir / f"{stem}.db"
        manifest_path = backup_dir / f"{stem}.json"

        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
        os.chmod(backup_path, 0o600)

        record = BackupRecord(
            database_path=str(database_path.resolve()),
            backup_path=str(backup_path.resolve()),
            manifest_path=str(manifest_path.resolve()),
            sha256=_file_sha256(backup_path),
            bytes=backup_path.stat().st_size,
            from_version=from_version,
            to_version=to_version,
            created_at_ms=created_at_ms,
        )
        manifest_path.write_text(json.dumps(asdict(record), indent=2, sort_keys=True) + "\n")
        os.chmod(manifest_path, 0o600)
        return record
    finally:
        source.close()


async def create_pre_migration_backup(
    database_path: Path, migrations: Sequence[Migration]
) -> BackupRecord | None:
    """Create a consistent backup only when an existing database needs migration."""

    return await asyncio.to_thread(_create_backup, database_path, migrations)


def restore_backup(backup_path: Path, database_path: Path, expected_sha256: str) -> Path | None:
    """Atomically restore a verified SQLite backup and retain the replaced database."""

    if backup_path.is_symlink():
        raise ValueError("Backup must be a regular file")
    backup_path = backup_path.resolve(strict=True)
    if database_path.is_symlink():
        raise ValueError("Database destination must not be a symlink")
    database_path = database_path.resolve(strict=False)
    if not backup_path.is_file():
        raise ValueError("Backup must be a regular file")
    if database_path.exists() and not database_path.is_file():
        raise ValueError("Database destination must be a regular file")
    if _file_sha256(backup_path) != expected_sha256:
        raise ValueError("Backup checksum does not match the recorded manifest")

    source = sqlite3.connect(f"{backup_path.as_uri()}?mode=ro", uri=True)
    try:
        integrity = source.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise ValueError("Backup integrity check failed")
    finally:
        source.close()

    database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    replacement = database_path.with_name(f".{database_path.name}.restore-{time.time_ns()}")
    source = sqlite3.connect(f"{backup_path.as_uri()}?mode=ro", uri=True)
    destination = sqlite3.connect(replacement)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    os.chmod(replacement, 0o600)
    displaced: Path | None = None
    displaced_sidecars: list[tuple[Path, Path]] = []
    planned_sidecars: list[tuple[Path, Path]] = []
    suffix = time.time_ns()
    for sidecar_suffix in ("-wal", "-shm", "-journal"):
        sidecar = database_path.with_name(database_path.name + sidecar_suffix)
        if sidecar.is_symlink():
            replacement.unlink(missing_ok=True)
            raise ValueError("Database journal must not be a symlink")
        if sidecar.exists():
            if not sidecar.is_file():
                replacement.unlink(missing_ok=True)
                raise ValueError("Database journal must be a regular file")
            retained = sidecar.with_name(f"{sidecar.name}.pre-restore-{suffix}")
            planned_sidecars.append((sidecar, retained))
    try:
        for sidecar, retained in planned_sidecars:
            sidecar.replace(retained)
            os.chmod(retained, 0o600)
            displaced_sidecars.append((sidecar, retained))
        if database_path.exists():
            displaced = database_path.with_name(f"{database_path.name}.pre-restore-{suffix}")
            database_path.replace(displaced)
            os.chmod(displaced, 0o600)
        replacement.replace(database_path)
    except BaseException:
        if displaced is not None and not database_path.exists():
            displaced.replace(database_path)
        for sidecar, retained in displaced_sidecars:
            if not sidecar.exists():
                retained.replace(sidecar)
        raise
    return displaced
