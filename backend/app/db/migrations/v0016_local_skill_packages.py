"""Make validated local skill content immutable and independently addressable."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE skill_package_files (
            skill_id TEXT NOT NULL REFERENCES skills(id),
            relative_path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            content TEXT NOT NULL,
            PRIMARY KEY (skill_id, relative_path)
        )
    """)
    await db.execute("CREATE INDEX idx_skill_package_files_skill ON skill_package_files(skill_id)")
    await db.execute("""
        CREATE TRIGGER skills_validated_fields_immutable
        BEFORE UPDATE OF manifest_json, content_hash, source_path ON skills
        BEGIN SELECT RAISE(ABORT, 'validated skill fields are immutable'); END
    """)
    await db.execute("""
        CREATE TRIGGER skill_package_files_immutable_update
        BEFORE UPDATE ON skill_package_files
        BEGIN SELECT RAISE(ABORT, 'skill package files are immutable'); END
    """)
    await db.execute("""
        CREATE TRIGGER skill_package_files_immutable_delete
        BEFORE DELETE ON skill_package_files
        BEGIN SELECT RAISE(ABORT, 'skill package files are immutable'); END
    """)
