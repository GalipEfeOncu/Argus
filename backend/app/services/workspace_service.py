"""Policy-aware project, workspace, tool, and writer-lease services.

All filesystem paths cross this module before being used.  It intentionally
uses argv execution (never a command shell) and rejects symbolic-link paths so
the resolved workspace boundary cannot be raced into another directory.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time
from typing import Iterable, Sequence
import uuid

import aiosqlite

from app.db.database import transaction
from app.db.repositories import _safe_json
from app.schemas.project import WorkspaceMode


class WorkspaceError(ValueError):
    """A safe, machine-readable workspace failure."""


class WorkspaceScopeError(WorkspaceError):
    pass


class WriterLeaseUnavailable(WorkspaceError):
    pass


class UnsupportedProject(WorkspaceError):
    pass


def _now_ms() -> int:
    return int(time.time() * 1000)


def _run(argv: Sequence[str], *, cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=False)


def _contains_symlink(root: Path) -> bool:
    if root.is_symlink():
        return True
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in [*directories, *files]:
            if (current_path / name).is_symlink():
                return True
    return False


def _case_sensitive(directory: Path) -> bool:
    """Probe a temporary sibling and remove it in all cases.

    Registration needs the actual filesystem behaviour rather than an OS
    guess; the marker never enters the project and is removed immediately.
    """

    marker = directory / f".argus-case-{uuid.uuid4().hex}a"
    alternate = directory / marker.name.swapcase()
    try:
        marker.touch(exist_ok=False)
        return not alternate.exists()
    except OSError as error:
        raise UnsupportedProject("project path does not permit case-sensitivity inspection") from error
    finally:
        marker.unlink(missing_ok=True)


def _workspace_checksum(root: Path) -> str:
    digest = sha256()
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories:
            if (current_path / name).is_symlink():
                raise WorkspaceScopeError("workspace contains symbolic links")
        directories[:] = sorted(name for name in directories if name != ".git")
        for name in sorted(files):
            path = current_path / name
            if path.is_symlink():
                raise WorkspaceScopeError("workspace contains symbolic links")
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def _copy_tree_without_symlinks(source: Path, destination: Path) -> None:
    """Copy a non-git project without following a source symlink race."""

    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        if _contains_symlink(source):
            raise UnsupportedProject("projects containing symbolic links are not supported")
        shutil.copytree(source, destination, symlinks=False)
        return
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.mkdir(mode=0o700)
    root_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def copy_directory(source_fd: int, target: Path) -> None:
        with os.scandir(os.dup(source_fd)) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise UnsupportedProject("projects containing symbolic links are not supported")
                target_path = target / entry.name
                if entry.is_dir(follow_symlinks=False):
                    target_path.mkdir(mode=0o700)
                    child_fd = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source_fd)
                    try:
                        copy_directory(child_fd, target_path)
                    finally:
                        os.close(child_fd)
                    continue
                source_file_fd = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_fd)
                try:
                    if not stat.S_ISREG(os.fstat(source_file_fd).st_mode):
                        raise UnsupportedProject("project contains an unsupported special file")
                    target_file_fd = os.open(target_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    try:
                        with os.fdopen(source_file_fd, "rb", closefd=False) as source_handle:
                            with os.fdopen(target_file_fd, "wb", closefd=False) as target_handle:
                                shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
                    finally:
                        os.close(target_file_fd)
                finally:
                    os.close(source_file_fd)

    try:
        copy_directory(root_fd, destination)
    finally:
        os.close(root_fd)


def resolve_workspace_path(root: Path, requested_path: str | Path, *, must_exist: bool = False) -> Path:
    """Resolve a relative tool target without allowing traversal or symlinks."""

    raw = Path(requested_path)
    if raw.is_absolute() or "\x00" in str(requested_path):
        raise WorkspaceScopeError("workspace paths must be relative")
    if ".." in raw.parts:
        raise WorkspaceScopeError("parent traversal is not allowed")
    canonical_root = root.resolve(strict=True)
    target = canonical_root.joinpath(raw)
    inspected = canonical_root
    for part in raw.parts:
        inspected = inspected / part
        if inspected.is_symlink():
            raise WorkspaceScopeError("symbolic links are not allowed in workspace paths")
    resolved = target.resolve(strict=must_exist)
    try:
        resolved.relative_to(canonical_root)
    except ValueError as error:
        raise WorkspaceScopeError("path escapes the session workspace") from error
    return resolved


def _relative_parts(requested_path: str | Path) -> tuple[str, ...]:
    raw = Path(requested_path)
    if raw.is_absolute() or "\x00" in str(requested_path) or ".." in raw.parts:
        raise WorkspaceScopeError("workspace paths must be relative and must not traverse parents")
    parts = tuple(part for part in raw.parts if part not in ("", "."))
    if not parts:
        raise WorkspaceScopeError("a file path is required")
    return parts


def _open_workspace_file(root: Path, requested_path: str | Path, *, write: bool) -> int:
    """Open a regular workspace file with descriptor-relative no-follow traversal.

    `Path.resolve()` is useful for diagnostics but cannot protect the gap before
    a later open.  This POSIX path walks each component from a directory fd with
    `O_NOFOLLOW`, so swapping any component for a symlink fails the operation.
    """

    parts = _relative_parts(requested_path)
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        # Windows does not offer descriptor-relative opens. It still receives
        # the strict canonical check rather than an unchecked host path.
        target = resolve_workspace_path(root, requested_path, must_exist=not write)
        if write:
            target.parent.mkdir(parents=True, exist_ok=True)
            return os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        return os.open(target, os.O_RDONLY)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory_fd = root_fd
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            except FileNotFoundError:
                if not write:
                    raise
                os.mkdir(part, mode=0o700, dir_fd=directory_fd)
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            if directory_fd != root_fd:
                os.close(directory_fd)
            directory_fd = next_fd
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC if write else os.O_RDONLY
        file_fd = os.open(parts[-1], flags | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            os.close(file_fd)
            raise WorkspaceScopeError("workspace target is not a regular file")
        return file_fd
    finally:
        if directory_fd != root_fd:
            os.close(directory_fd)
        os.close(root_fd)


@dataclass(frozen=True)
class ProjectInspection:
    canonical_path: str
    display_name: str
    git_metadata: dict[str, object]


@dataclass(frozen=True)
class WorkspaceRecord:
    session_id: str
    project_id: str
    mode: WorkspaceMode
    root_path: Path
    baseline_path: Path | None
    revision_checksum: str


class ProjectWorkspaceService:
    def __init__(self, db: aiosqlite.Connection, *, managed_root: Path) -> None:
        self._db = db
        self._managed_root = managed_root

    def inspect_project(self, requested_path: str, display_name: str | None = None) -> ProjectInspection:
        source = Path(requested_path).expanduser()
        if not source.exists() or not source.is_dir():
            raise UnsupportedProject("project path must be an existing directory")
        canonical = source.resolve(strict=True)
        if canonical == canonical.parent:
            raise UnsupportedProject("filesystem roots are not supported as projects")
        contains_symlinks = _contains_symlink(source)
        git = _run(["git", "rev-parse", "--show-toplevel"], cwd=canonical)
        is_git = git.returncode == 0
        metadata: dict[str, object] = {
            "isGit": is_git,
            "rootPath": None,
            "head": None,
            "dirty": False,
            "nestedRepositoryPaths": [],
            "containsSymlinks": contains_symlinks,
            "caseSensitive": _case_sensitive(canonical),
        }
        if is_git:
            git_root = Path(git.stdout.strip()).resolve(strict=True)
            if git_root != canonical:
                raise UnsupportedProject("project path must be the root of its git repository")
            metadata["rootPath"] = str(git_root)
            head = _run(["git", "rev-parse", "HEAD"], cwd=canonical)
            metadata["head"] = head.stdout.strip() if head.returncode == 0 else None
            metadata["dirty"] = bool(_run(["git", "status", "--porcelain=v1"], cwd=canonical).stdout.strip())
            nested: list[str] = []
            for current, directories, _ in os.walk(canonical, followlinks=False):
                directories[:] = [name for name in directories if name not in {".git", ".argus"}]
                current_path = Path(current)
                if current_path == canonical:
                    continue
                nested_git = current_path / ".git"
                if nested_git.exists():
                    nested.append(current_path.relative_to(canonical).as_posix())
                    directories.clear()
            metadata["nestedRepositoryPaths"] = sorted(nested)
        return ProjectInspection(str(canonical), display_name or canonical.name, metadata)

    async def register_project(self, requested_path: str, display_name: str | None = None) -> dict[str, object]:
        inspection = await asyncio.to_thread(self.inspect_project, requested_path, display_name)
        now = _now_ms()
        async with transaction(self._db):
            async with self._db.execute("SELECT * FROM projects WHERE canonical_path = ?", (inspection.canonical_path,)) as cursor:
                current = await cursor.fetchone()
            if current is None:
                project_id = str(uuid.uuid4())
                await self._db.execute(
                    """INSERT INTO projects (id, canonical_path, display_name, git_metadata_json, created_at_ms, updated_at_ms)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (project_id, inspection.canonical_path, inspection.display_name, _safe_json(inspection.git_metadata), now, now),
                )
            else:
                project_id = current["id"]
                await self._db.execute(
                    "UPDATE projects SET display_name = ?, git_metadata_json = ?, updated_at_ms = ? WHERE id = ?",
                    (inspection.display_name, _safe_json(inspection.git_metadata), now, project_id),
                )
            return {"id": project_id, "canonicalPath": inspection.canonical_path, "displayName": inspection.display_name,
                    "gitMetadata": inspection.git_metadata, "createdAtMs": now if current is None else current["created_at_ms"], "updatedAtMs": now}

    async def list_projects(self) -> list[dict[str, object]]:
        async with self._db.execute("SELECT * FROM projects ORDER BY updated_at_ms DESC, id DESC") as cursor:
            rows = await cursor.fetchall()
        return [{"id": row["id"], "canonicalPath": row["canonical_path"], "displayName": row["display_name"],
                 "gitMetadata": json.loads(row["git_metadata_json"]), "createdAtMs": row["created_at_ms"], "updatedAtMs": row["updated_at_ms"]} for row in rows]

    async def prepare_workspace(self, *, session_id: str, project_id: str, mode: WorkspaceMode,
                                acknowledged_direct_write: bool = False) -> WorkspaceRecord:
        async with self._db.execute("SELECT canonical_path, git_metadata_json FROM projects WHERE id = ?", (project_id,)) as cursor:
            project = await cursor.fetchone()
        if project is None:
            raise WorkspaceError("project not found")
        source = Path(project["canonical_path"])
        metadata = json.loads(project["git_metadata_json"])
        if metadata["containsSymlinks"]:
            raise UnsupportedProject("projects containing symbolic links are not supported")
        if mode is WorkspaceMode.worktree and not metadata["isGit"]:
            raise UnsupportedProject("worktree mode requires a git project")
        if mode is WorkspaceMode.snapshot and metadata["isGit"]:
            raise UnsupportedProject("git projects use worktree mode by default")
        if mode is WorkspaceMode.direct_write and not acknowledged_direct_write:
            raise WorkspaceError("direct_write requires an explicit acknowledgement")
        self._managed_root.mkdir(parents=True, exist_ok=True)
        root = source if mode is WorkspaceMode.direct_write else self._managed_root / session_id / "workspace"
        baseline: Path | None = None
        try:
            if mode is WorkspaceMode.worktree:
                root.parent.mkdir(parents=True, exist_ok=True)
                branch = f"argus/{session_id}"
                result = await asyncio.to_thread(_run, ["git", "worktree", "add", "-b", branch, str(root), "HEAD"], cwd=source, timeout=60)
                if result.returncode != 0:
                    raise WorkspaceError(f"worktree creation failed: {result.stderr.strip()}")
            elif mode is WorkspaceMode.snapshot:
                baseline = self._managed_root / session_id / "baseline"
                await asyncio.to_thread(_copy_tree_without_symlinks, source, root)
                await asyncio.to_thread(_copy_tree_without_symlinks, source, baseline)
            revision = await asyncio.to_thread(_workspace_checksum, root)
        except BaseException:
            if mode is WorkspaceMode.worktree and root.exists():
                await asyncio.to_thread(_run, ["git", "worktree", "remove", "--force", str(root)], cwd=source)
            elif root != source:
                await asyncio.to_thread(shutil.rmtree, root.parent, True)
            raise
        now = _now_ms()
        async with transaction(self._db):
            await self._db.execute("DELETE FROM workspaces WHERE session_id = ?", (session_id,))
            await self._db.execute(
                """INSERT INTO workspaces (session_id, project_id, mode, root_path, baseline_path, revision_checksum, created_at_ms, updated_at_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, project_id, mode.value, str(root), None if baseline is None else str(baseline), revision, now, now),
            )
            await self._audit(session_id, "workspace.prepared", {"mode": mode.value, "revisionChecksum": revision})
        return WorkspaceRecord(session_id, project_id, mode, root, baseline, revision)

    async def workspace_for_session(self, session_id: str) -> WorkspaceRecord:
        async with self._db.execute("SELECT * FROM workspaces WHERE session_id = ? AND cleaned_at_ms IS NULL", (session_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise WorkspaceError("session workspace not found")
        return WorkspaceRecord(row["session_id"], row["project_id"], WorkspaceMode(row["mode"]), Path(row["root_path"]),
                               None if row["baseline_path"] is None else Path(row["baseline_path"]), row["revision_checksum"])

    async def acquire_writer_lease(self, *, project_id: str, session_id: str, holder_id: str, ttl_ms: int = 60_000) -> str:
        if ttl_ms < 1_000:
            raise WorkspaceError("writer lease TTL must be at least 1000ms")
        now = _now_ms()
        async with transaction(self._db):
            await self._recover_expired_leases(project_id, now)
            async with self._db.execute("SELECT lock_session_id FROM projects WHERE id = ?", (project_id,)) as cursor:
                project = await cursor.fetchone()
            if project is None:
                raise WorkspaceError("project not found")
            if project["lock_session_id"] not in (None, session_id):
                raise WriterLeaseUnavailable("project writer lock is held by another session")
            async with self._db.execute("SELECT id, holder_id, expires_at_ms FROM writer_leases WHERE project_id = ? AND released_at_ms IS NULL", (project_id,)) as cursor:
                lease = await cursor.fetchone()
            if lease is not None and lease["holder_id"] != holder_id:
                raise WriterLeaseUnavailable("session writer lease is held by another participant")
            lease_id = lease["id"] if lease is not None else str(uuid.uuid4())
            expires = now + ttl_ms
            if lease is None:
                await self._db.execute("INSERT INTO writer_leases (id, project_id, session_id, holder_id, acquired_at_ms, expires_at_ms, renewed_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                       (lease_id, project_id, session_id, holder_id, now, expires, now))
            else:
                await self._db.execute("UPDATE writer_leases SET expires_at_ms = ?, renewed_at_ms = ? WHERE id = ?", (expires, now, lease_id))
            await self._db.execute("UPDATE projects SET lock_session_id = ?, lock_acquired_at_ms = ?, updated_at_ms = ? WHERE id = ?", (session_id, now, now, project_id))
            await self._audit(session_id, "writer_lease.acquired", {"leaseId": lease_id, "holderId": holder_id, "expiresAtMs": expires})
        return lease_id

    async def renew_writer_lease(self, lease_id: str, *, holder_id: str, ttl_ms: int = 60_000) -> None:
        now = _now_ms()
        async with transaction(self._db):
            async with self._db.execute("SELECT session_id, holder_id, expires_at_ms FROM writer_leases WHERE id = ? AND released_at_ms IS NULL", (lease_id,)) as cursor:
                lease = await cursor.fetchone()
            if lease is None or lease["holder_id"] != holder_id or lease["expires_at_ms"] <= now:
                raise WriterLeaseUnavailable("writer lease is no longer active")
            expires = now + ttl_ms
            await self._db.execute("UPDATE writer_leases SET expires_at_ms = ?, renewed_at_ms = ? WHERE id = ?", (expires, now, lease_id))
            await self._audit(lease["session_id"], "writer_lease.renewed", {"leaseId": lease_id, "expiresAtMs": expires})

    async def release_writer_lease(self, lease_id: str, *, holder_id: str, reason: str) -> bool:
        now = _now_ms()
        async with transaction(self._db):
            async with self._db.execute("SELECT project_id, session_id, holder_id FROM writer_leases WHERE id = ? AND released_at_ms IS NULL", (lease_id,)) as cursor:
                lease = await cursor.fetchone()
            if lease is None or lease["holder_id"] != holder_id:
                return False
            await self._db.execute("UPDATE writer_leases SET released_at_ms = ?, release_reason = ? WHERE id = ?", (now, reason, lease_id))
            await self._db.execute("UPDATE projects SET lock_session_id = NULL, lock_acquired_at_ms = NULL, updated_at_ms = ? WHERE id = ? AND lock_session_id = ?", (now, lease["project_id"], lease["session_id"]))
            await self._audit(lease["session_id"], "writer_lease.released", {"leaseId": lease_id, "reason": reason})
            return True

    async def record_mutation(self, session_id: str) -> str:
        workspace = await self.workspace_for_session(session_id)
        revision = await asyncio.to_thread(_workspace_checksum, workspace.root_path)
        if revision == workspace.revision_checksum:
            return revision
        diff_summary = await asyncio.to_thread(self._diff_summary, workspace)
        now = _now_ms()
        async with transaction(self._db):
            await self._db.execute("UPDATE workspaces SET revision_checksum = ?, updated_at_ms = ? WHERE session_id = ?", (revision, now, session_id))
            await self._db.execute("INSERT OR IGNORE INTO artifacts (id, session_id, kind, checksum, metadata_json, created_at_ms) VALUES (?, ?, 'diff', ?, ?, ?)",
                                   (str(uuid.uuid4()), session_id, revision, _safe_json({"summary": diff_summary, "workspaceRevision": revision}), now))
            await self._audit(session_id, "workspace.mutated", {"revisionChecksum": revision, "diffSummary": diff_summary})
        return revision

    def _diff_summary(self, workspace: WorkspaceRecord) -> str:
        if workspace.mode in (WorkspaceMode.worktree, WorkspaceMode.direct_write):
            result = _run(["git", "diff", "--stat", "--no-ext-diff"], cwd=workspace.root_path)
            if result.returncode == 0:
                return result.stdout[:4000]
        return "workspace content changed"

    async def cleanup_workspace(self, session_id: str) -> None:
        workspace = await self.workspace_for_session(session_id)
        if workspace.mode is WorkspaceMode.worktree:
            project = await self._project_path(workspace.project_id)
            await asyncio.to_thread(_run, ["git", "worktree", "remove", "--force", str(workspace.root_path)], cwd=project)
            await asyncio.to_thread(_run, ["git", "branch", "-D", f"argus/{session_id}"], cwd=project)
        elif workspace.mode is WorkspaceMode.snapshot:
            await asyncio.to_thread(shutil.rmtree, workspace.root_path.parent, True)
        now = _now_ms()
        async with transaction(self._db):
            await self._db.execute("UPDATE workspaces SET cleaned_at_ms = ? WHERE session_id = ?", (now, session_id))
            await self._audit(session_id, "workspace.cleaned", {})

    async def recover_after_restart(self) -> None:
        """Release expired locks and remove managed directories left before DB commit.

        A persisted workspace is intentionally retained across a sidecar restart;
        only an unregistered managed directory can be an interrupted setup.
        """

        now = _now_ms()
        async with transaction(self._db):
            async with self._db.execute("SELECT DISTINCT project_id FROM writer_leases WHERE released_at_ms IS NULL AND expires_at_ms <= ?", (now,)) as cursor:
                project_ids = [row["project_id"] for row in await cursor.fetchall()]
            for project_id in project_ids:
                await self._recover_expired_leases(project_id, now)
            async with self._db.execute("SELECT session_id FROM workspaces WHERE cleaned_at_ms IS NULL") as cursor:
                active_sessions = {row["session_id"] for row in await cursor.fetchall()}
        if self._managed_root.exists():
            for child in self._managed_root.iterdir():
                if not child.is_dir() or child.is_symlink() or child.name in active_sessions:
                    continue
                await asyncio.to_thread(shutil.rmtree, child, True)
        async with self._db.execute("SELECT canonical_path FROM projects WHERE json_extract(git_metadata_json, '$.isGit') = 1") as cursor:
            git_projects = [Path(row["canonical_path"]) for row in await cursor.fetchall()]
        for project in git_projects:
            await asyncio.to_thread(_run, ["git", "worktree", "prune"], cwd=project)

    async def _project_path(self, project_id: str) -> Path:
        async with self._db.execute("SELECT canonical_path FROM projects WHERE id = ?", (project_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise WorkspaceError("project not found")
        return Path(row["canonical_path"])

    async def _recover_expired_leases(self, project_id: str, now: int) -> None:
        async with self._db.execute("SELECT id, session_id FROM writer_leases WHERE project_id = ? AND released_at_ms IS NULL AND expires_at_ms <= ?", (project_id, now)) as cursor:
            expired = await cursor.fetchall()
        for lease in expired:
            await self._db.execute("UPDATE writer_leases SET released_at_ms = ?, release_reason = 'expired_recovery' WHERE id = ?", (now, lease["id"]))
            await self._audit(lease["session_id"], "writer_lease.recovered", {"leaseId": lease["id"]})
        if expired:
            await self._db.execute("UPDATE projects SET lock_session_id = NULL, lock_acquired_at_ms = NULL, updated_at_ms = ? WHERE id = ?", (now, project_id))

    async def _audit(self, session_id: str, action: str, detail: dict[str, object]) -> None:
        await self._db.execute("INSERT INTO workspace_audit (id, session_id, action, detail_json, created_at_ms) VALUES (?, ?, ?, ?, ?)",
                               (str(uuid.uuid4()), session_id, action, _safe_json(detail), _now_ms()))


class ScopedToolService:
    """Small argv-only execution surface used by worker tool adapters."""

    def __init__(self, workspace: WorkspaceRecord) -> None:
        self._workspace = workspace

    def read_text(self, path: str) -> str:
        try:
            file_fd = _open_workspace_file(self._workspace.root_path, path, write=False)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise WorkspaceScopeError("symbolic links are not allowed in workspace paths") from error
            raise
        with os.fdopen(file_fd, "r", encoding="utf-8") as handle:
            return handle.read()

    def write_text(self, path: str, content: str) -> None:
        try:
            file_fd = _open_workspace_file(self._workspace.root_path, path, write=True)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise WorkspaceScopeError("symbolic links are not allowed in workspace paths") from error
            raise
        with os.fdopen(file_fd, "w", encoding="utf-8") as handle:
            handle.write(content)

    def run(self, argv: Sequence[str], *, timeout_seconds: int = 60, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        if not argv or any(not isinstance(part, str) or "\x00" in part for part in argv):
            raise WorkspaceError("tool command must be a non-empty argv list")
        executable = Path(argv[0]).name.lower()
        destructive = {"rm", "rmdir", "mkfs", "dd", "shutdown", "reboot", "poweroff", "sh", "bash", "zsh", "cmd", "powershell"}
        if executable in destructive:
            raise WorkspaceError("destructive command denied")
        allowed = {"rg", "pytest", "npm", "pnpm", "yarn", "cargo", "go", "gradle", "mvn", "make", "tox", "env", "git"}
        if executable not in allowed:
            raise WorkspaceError("command denied outside the workspace policy")
        if any(Path(argument).is_absolute() or ".." in Path(argument).parts for argument in argv[1:]):
            raise WorkspaceScopeError("command arguments must not reference paths outside the workspace")
        if executable == "git":
            allowed_git_options = {
                "status": {"--short", "--no-untracked-files"},
                "diff": {"--stat", "--no-ext-diff"},
            }
            if len(argv) < 2 or argv[1] not in allowed_git_options or any(argument not in allowed_git_options[argv[1]] for argument in argv[2:]):
                raise WorkspaceError("git command denied by workspace policy")
        if executable == "rg" and any(argument == "--pre" or argument.startswith("--pre=") for argument in argv[1:]):
            raise WorkspaceError("ripgrep preprocessor denied by workspace policy")
        if executable == "env" and len(argv) != 1:
            raise WorkspaceError("environment inspection does not accept arguments")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": os.environ.get("LANG", "C"),
        }
        env.update({key: value for key, value in (environment or {}).items()
                    if not any(token in key.lower() for token in ("secret", "token", "password", "key", "credential"))})
        # `rg`, a zero-argument environment probe, and the narrow git read
        # operations above do not execute project code and have fully scoped
        # operands. Test/build commands do execute project-controlled code, so
        # they never run directly on the host.
        directly_scoped = executable in {"rg", "env", "git"}
        if directly_scoped:
            return subprocess.run(list(argv), cwd=self._workspace.root_path, capture_output=True, text=True, timeout=timeout_seconds, shell=False, env=env)
        bubblewrap = shutil.which("bwrap")
        if bubblewrap is None:
            raise WorkspaceError("command denied because no workspace sandbox is available")
        sandbox_argv = [
            bubblewrap, "--die-with-parent", "--unshare-all", "--new-session", "--tmpfs", "/", "--tmpfs", "/tmp",
            "--proc", "/proc", "--dev", "/dev", "--bind", str(self._workspace.root_path), "/workspace",
            "--chdir", "/workspace",
        ]
        for runtime_path in ("/usr", "/bin", "/lib", "/lib64"):
            if Path(runtime_path).exists():
                sandbox_argv.extend(("--ro-bind", runtime_path, runtime_path))
        sandbox_argv.extend(("--", *argv))
        return subprocess.run(sandbox_argv, capture_output=True, text=True, timeout=timeout_seconds, shell=False, env=env)
