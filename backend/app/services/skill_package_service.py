"""Import local skill packages into immutable SQLite snapshots.

The importer deliberately never executes package content.  A package's text is
untrusted model context; declared tools and permissions are checked later
against the immutable session agent and are never inferred from instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import stat
import uuid

import aiosqlite
from pydantic import ValidationError

from app.db.database import transaction
from app.db.repositories import _now_ms, _safe_json
from app.schemas.skill import SkillImportRequest, SkillManifest, SkillPackageResponse
from app.services.session_configuration_service import ConfigurationError


_KNOWN_TOOLS = frozenset({"read_file", "write_file", "edit_file", "list_dir", "search_files", "shell_exec", "git_status", "git_diff"})
_KNOWN_PERMISSIONS = frozenset({"workspace.read", "workspace.write", "test.run", "search.files"})
_MAX_FILES = 100
_MAX_FILE_BYTES = 1_000_000
_MAX_PACKAGE_BYTES = 4_000_000


@dataclass(frozen=True)
class SkillSnapshot:
    id: str
    version: str
    content_hash: str
    instructions: str
    references: tuple[dict[str, str], ...]
    requested_tools: tuple[str, ...]
    requested_permissions: tuple[str, ...]

    def value(self) -> dict[str, object]:
        return {
            "id": self.id, "version": self.version, "contentHash": self.content_hash,
            "instructions": self.instructions, "references": list(self.references),
            "requestedTools": list(self.requested_tools), "requestedPermissions": list(self.requested_permissions),
        }


class SkillPackageService:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def list(self) -> list[SkillPackageResponse]:
        async with self._db.execute("SELECT * FROM skills ORDER BY created_at_ms DESC, id") as cursor:
            return [self._response(row) for row in await cursor.fetchall()]

    async def import_package(self, request: SkillImportRequest) -> SkillPackageResponse:
        source_path, files, manifest = self._validate_package(request.source_path)
        canonical_source = source_path
        aggregate = sha256()
        for relative_path, content in files.items():
            aggregate.update(relative_path.encode("utf-8"))
            aggregate.update(b"\0")
            aggregate.update(sha256(content.encode("utf-8")).digest())
        content_hash = aggregate.hexdigest()
        async with self._db.execute("SELECT * FROM skills WHERE source_path = ?", (canonical_source,)) as cursor:
            same_source = await cursor.fetchone()
        if same_source is not None:
            if str(same_source["content_hash"]) == content_hash:
                return self._response(same_source)
            raise ConfigurationError("skill_source_changed", "This source was already imported with different immutable content; import a new package directory.")
        async with self._db.execute("SELECT * FROM skills WHERE content_hash = ?", (content_hash,)) as cursor:
            same_content = await cursor.fetchone()
        if same_content is not None:
            return self._response(same_content)
        skill_id = f"skl_{uuid.uuid4().hex}"
        now = _now_ms()
        manifest_value = manifest.model_dump(by_alias=True, mode="json")
        async with transaction(self._db):
            await self._db.execute(
                """INSERT INTO skills (id, manifest_json, content_hash, trust_state, source_path, enabled, created_at_ms, updated_at_ms)
                   VALUES (?, ?, ?, 'review_required', ?, 0, ?, ?)""",
                (skill_id, _safe_json(manifest_value), content_hash, canonical_source, now, now),
            )
            for relative_path, content in files.items():
                await self._db.execute(
                    "INSERT INTO skill_package_files (skill_id, relative_path, content_hash, content) VALUES (?, ?, ?, ?)",
                    (skill_id, relative_path, sha256(content.encode("utf-8")).hexdigest(), content),
                )
        async with self._db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)) as cursor:
            return self._response(await cursor.fetchone())

    async def set_enabled(self, skill_id: str, enabled: bool) -> SkillPackageResponse:
        async with transaction(self._db):
            async with self._db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise ConfigurationError("skill_not_found", "The local skill package was not found.")
            await self._db.execute(
                "UPDATE skills SET enabled = ?, trust_state = ?, updated_at_ms = ? WHERE id = ?",
                (int(enabled), "enabled" if enabled else "review_required", _now_ms(), skill_id),
            )
        async with self._db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)) as cursor:
            updated = await cursor.fetchone()
        assert updated is not None
        return self._response(updated)

    async def snapshots_for_agent(self, skill_ids: list[str], *, tool_allowlist: list[str], capabilities: list[str]) -> list[dict[str, object]]:
        """Resolve only enabled, stored content and reject any policy expansion."""
        if len(set(skill_ids)) != len(skill_ids):
            raise ConfigurationError("duplicate_skill_id", "An agent cannot select the same local skill package more than once.")
        snapshots: list[dict[str, object]] = []
        for skill_id in skill_ids:
            async with self._db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise ConfigurationError("skill_not_found", "An agent references a missing local skill package.")
            if not bool(row["enabled"]):
                raise ConfigurationError("skill_not_enabled", "An agent can only use an explicitly enabled local skill package.")
            manifest = SkillManifest.model_validate(json.loads(row["manifest_json"]))
            if not set(manifest.requested_tools).issubset(tool_allowlist):
                raise ConfigurationError("skill_tool_escalation", "A skill requests a tool outside its immutable agent allowlist.")
            if not set(manifest.requested_permissions).issubset(capabilities):
                raise ConfigurationError("skill_permission_escalation", "A skill requests permissions outside its immutable agent capabilities.")
            async with self._db.execute("SELECT relative_path, content FROM skill_package_files WHERE skill_id = ? ORDER BY relative_path", (skill_id,)) as cursor:
                content = {str(item["relative_path"]): str(item["content"]) for item in await cursor.fetchall()}
            instructions = content.get(manifest.instructions)
            if instructions is None:
                raise ConfigurationError("skill_snapshot_invalid", "The imported skill instructions are unavailable.")
            references = tuple({"path": reference, "content": content[reference]} for reference in manifest.references)
            snapshots.append(SkillSnapshot(
                skill_id, manifest.version, str(row["content_hash"]), instructions, references,
                tuple(manifest.requested_tools), tuple(manifest.requested_permissions),
            ).value())
        return snapshots

    @staticmethod
    def _validate_package(source_path: str) -> tuple[str, dict[str, str], SkillManifest]:
        raw_root = Path(source_path)
        if not raw_root.is_absolute():
            raise ConfigurationError("invalid_skill_source", "A skill source must be an existing, non-symlink absolute directory.")
        # Open the user-selected root once. Do not resolve/check it by pathname
        # first: that would permit a root replacement race before traversal.
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            root_fd = os.open(raw_root, directory_flags)
        except OSError as error:
            raise ConfigurationError("invalid_skill_source", "A skill source must be a readable non-symlink directory.") from error
        try:
            if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
                raise ConfigurationError("invalid_skill_source", "A skill source must be a readable non-symlink directory.")
            collected = _read_package_tree_fd(root_fd)
        finally:
            os.close(root_fd)
        raw_manifest = collected.get("skill.json")
        if raw_manifest is None:
            raise ConfigurationError("skill_manifest_missing", "A local skill package requires skill.json.")
        try:
            manifest = SkillManifest.model_validate_json(raw_manifest)
        except ValidationError as error:
            raise ConfigurationError("invalid_skill_manifest", "The local skill manifest does not match schema version 1.") from error
        referenced = [manifest.instructions, *manifest.references]
        if len(set(referenced)) != len(referenced) or any(not _safe_relative_path(path) or path not in collected for path in referenced):
            raise ConfigurationError("invalid_skill_reference", "Every instruction and reference path must be a unique file inside the package.")
        if not set(manifest.requested_tools).issubset(_KNOWN_TOOLS):
            raise ConfigurationError("unknown_skill_tool", "The skill manifest requests an unsupported tool.")
        if not set(manifest.requested_permissions).issubset(_KNOWN_PERMISSIONS):
            raise ConfigurationError("unknown_skill_permission", "The skill manifest requests an unsupported permission.")
        # This is display/audit metadata only; active sessions never re-open
        # it. Keeping the original absolute spelling avoids a second pathname
        # resolution that could race the descriptor-bound import.
        return str(raw_root), dict(sorted(collected.items())), manifest

    @staticmethod
    def _response(row: aiosqlite.Row) -> SkillPackageResponse:
        manifest = SkillManifest.model_validate(json.loads(row["manifest_json"]))
        return SkillPackageResponse.model_validate({
            "id": str(row["id"]), "manifest": manifest.model_dump(by_alias=True), "contentHash": str(row["content_hash"]),
            "trustState": "enabled" if bool(row["enabled"]) else "review_required", "sourcePath": str(row["source_path"]),
            "enabled": bool(row["enabled"]), "createdAtMs": int(row["created_at_ms"]),
            "requestedTools": manifest.requested_tools, "requestedPermissions": manifest.requested_permissions,
        })


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and path.as_posix() not in {".", ""}


def _read_package_tree_fd(root_fd: int) -> dict[str, str]:
    """Copy a tree through directory descriptors, never path re-resolution.

    ``O_NOFOLLOW`` on the leaf alone is insufficient because an attacker could
    replace an already-listed parent directory.  Opening every component from
    its still-open parent descriptor prevents that symlink escape race.
    """
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    files: dict[str, str] = {}
    total = 0

    def visit(directory_fd: int, prefix: PurePosixPath) -> None:
        nonlocal total
        for name in sorted(os.listdir(directory_fd)):
            relative = (prefix / name).as_posix()
            if not _safe_relative_path(relative):
                raise ConfigurationError("invalid_skill_path", "Skill package paths must stay inside the package directory.")
            try:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as error:
                raise ConfigurationError("invalid_skill_file", "Skill package files must remain readable while importing.") from error
            if stat.S_ISLNK(info.st_mode):
                raise ConfigurationError("skill_symlink_forbidden", "Skill packages cannot contain symlinks.")
            if stat.S_ISDIR(info.st_mode):
                try:
                    child_fd = os.open(name, directory_flags, dir_fd=directory_fd)
                except OSError as error:
                    raise ConfigurationError("skill_symlink_forbidden", "Skill packages cannot contain symlinked directories.") from error
                try:
                    visit(child_fd, PurePosixPath(relative))
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ConfigurationError("invalid_skill_file", "Skill packages may contain regular text files only.")
            try:
                file_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), dir_fd=directory_fd)
            except OSError as error:
                raise ConfigurationError("invalid_skill_file", "Skill package files may contain regular readable files only.") from error
            try:
                actual = os.fstat(file_fd)
                if not stat.S_ISREG(actual.st_mode):
                    raise ConfigurationError("invalid_skill_file", "Skill packages may contain regular text files only.")
                content_bytes = os.read(file_fd, _MAX_FILE_BYTES + 1)
            finally:
                os.close(file_fd)
            total += len(content_bytes)
            if actual.st_size > _MAX_FILE_BYTES or len(content_bytes) > _MAX_FILE_BYTES or total > _MAX_PACKAGE_BYTES or len(files) >= _MAX_FILES:
                raise ConfigurationError("skill_package_too_large", "The local skill package exceeds the supported size limit.")
            try:
                files[relative] = content_bytes.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ConfigurationError("skill_content_not_text", "Skill package files must be UTF-8 text.") from error

    visit(root_fd, PurePosixPath())
    return dict(sorted(files.items()))
