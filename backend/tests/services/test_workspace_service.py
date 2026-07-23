from __future__ import annotations

from pathlib import Path
import subprocess
import threading
import asyncio

import pytest

from app.db.database import get_db
from app.db.repositories import SessionRepository
from app.schemas.project import WorkspaceMode
from app.services.workspace_service import (
    ProjectWorkspaceService,
    ScopedToolService,
    WorkspaceError,
    WorkspaceScopeError,
    WriterLeaseUnavailable,
)
from app.tools.scoped_tools import create_scoped_tools


async def _session(database, session_id: str) -> None:
    await SessionRepository(database).create_legacy_session(
        session_id=session_id, name=session_id, project_path="workspace", task="test", role_configs=[]
    )


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True)


def _git_project(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "argus-test@example.invalid")
    _git(path, "config", "user.name", "Argus Test")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial")


@pytest.mark.asyncio
async def test_registers_canonical_git_project_and_reports_dirty_nested_and_case_metadata(temporary_sqlite_db, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _git_project(project)
    nested = project / "vendor" / "nested"
    nested.mkdir(parents=True)
    _git_project(nested)
    (project / "README.md").write_text("dirty\n", encoding="utf-8")
    database = await get_db()
    try:
        service = ProjectWorkspaceService(database, managed_root=tmp_path / "managed")
        registered = await service.register_project(str(project / "."))
        duplicate = await service.register_project(str(project))
    finally:
        await database.close()

    assert registered["id"] == duplicate["id"]
    assert registered["canonicalPath"] == str(project.resolve())
    metadata = registered["gitMetadata"]
    assert metadata["isGit"] is True and metadata["dirty"] is True
    assert metadata["nestedRepositoryPaths"] == ["vendor/nested"]
    assert isinstance(metadata["caseSensitive"], bool)


@pytest.mark.asyncio
async def test_non_git_snapshot_is_isolated_and_direct_write_requires_acknowledgement(temporary_sqlite_db, tmp_path: Path) -> None:
    project = tmp_path / "plain"
    project.mkdir()
    (project / "input.txt").write_text("original\n", encoding="utf-8")
    database = await get_db()
    try:
        await _session(database, "snapshot-session")
        service = ProjectWorkspaceService(database, managed_root=tmp_path / "managed")
        registered = await service.register_project(str(project))
        with pytest.raises(WorkspaceError, match="explicit acknowledgement"):
            await service.prepare_workspace(session_id="snapshot-session", project_id=registered["id"], mode=WorkspaceMode.direct_write)
        workspace = await service.prepare_workspace(session_id="snapshot-session", project_id=registered["id"], mode=WorkspaceMode.snapshot)
        ScopedToolService(workspace).write_text("input.txt", "isolated\n")
        revision = await service.record_mutation("snapshot-session")
    finally:
        await database.close()

    assert (project / "input.txt").read_text(encoding="utf-8") == "original\n"
    assert (workspace.root_path / "input.txt").read_text(encoding="utf-8") == "isolated\n"
    assert revision != workspace.revision_checksum


@pytest.mark.asyncio
async def test_git_worktree_is_managed_and_cleanup_preserves_the_original_project(temporary_sqlite_db, tmp_path: Path) -> None:
    project = tmp_path / "git-project"
    project.mkdir()
    _git_project(project)
    database = await get_db()
    try:
        await _session(database, "worktree-session")
        service = ProjectWorkspaceService(database, managed_root=tmp_path / "managed")
        registered = await service.register_project(str(project))
        workspace = await service.prepare_workspace(session_id="worktree-session", project_id=registered["id"], mode=WorkspaceMode.worktree)
        ScopedToolService(workspace).write_text("README.md", "changed in worktree\n")
        revision = await service.record_mutation("worktree-session")
        await service.cleanup_workspace("worktree-session")
    finally:
        await database.close()

    assert revision != workspace.revision_checksum
    assert (project / "README.md").read_text(encoding="utf-8") == "base\n"
    assert not workspace.root_path.exists()
    assert "argus/worktree-session" not in subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=project, capture_output=True, text=True, check=True).stdout


@pytest.mark.asyncio
async def test_direct_write_is_available_only_after_acknowledgement_and_is_audited(temporary_sqlite_db, tmp_path: Path) -> None:
    project = tmp_path / "plain"
    project.mkdir()
    database = await get_db()
    try:
        await _session(database, "direct-session")
        service = ProjectWorkspaceService(database, managed_root=tmp_path / "managed")
        registered = await service.register_project(str(project))
        workspace = await service.prepare_workspace(session_id="direct-session", project_id=registered["id"], mode=WorkspaceMode.direct_write, acknowledged_direct_write=True)
        ScopedToolService(workspace).write_text("acknowledged.txt", "written\n")
        await service.record_mutation("direct-session")
        async with database.execute("SELECT action FROM workspace_audit WHERE session_id = 'direct-session'") as cursor:
            actions = {row["action"] for row in await cursor.fetchall()}
    finally:
        await database.close()

    assert (project / "acknowledged.txt").read_text(encoding="utf-8") == "written\n"
    assert {"workspace.prepared", "workspace.mutated"} <= actions


@pytest.mark.asyncio
async def test_scoped_mutating_tool_uses_writer_lease_and_persists_revision_artifact(temporary_sqlite_db, tmp_path: Path) -> None:
    project = tmp_path / "plain"
    project.mkdir()
    database = await get_db()
    try:
        await _session(database, "tool-mutation")
        service = ProjectWorkspaceService(database, managed_root=tmp_path / "managed")
        registered = await service.register_project(str(project))
        workspace = await service.prepare_workspace(session_id="tool-mutation", project_id=registered["id"], mode=WorkspaceMode.snapshot)
        by_name = {tool.name: tool for tool in create_scoped_tools(workspace)}
        assert await by_name["write_file"].ainvoke({"path": "created.txt", "content": "tracked\n"}) == "Written created.txt"
        async with database.execute("SELECT checksum FROM artifacts WHERE session_id = 'tool-mutation' AND kind = 'diff'") as cursor:
            artifact = await cursor.fetchone()
        async with database.execute("SELECT action FROM workspace_audit WHERE session_id = 'tool-mutation'") as cursor:
            actions = {row["action"] for row in await cursor.fetchall()}
        async with database.execute("SELECT COUNT(*) AS total FROM writer_leases WHERE session_id = 'tool-mutation' AND released_at_ms IS NULL") as cursor:
            active_leases = (await cursor.fetchone())["total"]
    finally:
        await database.close()

    assert artifact is not None
    assert "writer_lease.acquired" in actions and "writer_lease.released" in actions
    assert active_leases == 0


@pytest.mark.asyncio
async def test_workspace_tools_reject_escape_symlink_shell_injection_secrets_and_destructive_commands(temporary_sqlite_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "plain"
    project.mkdir()
    (project / "safe.txt").write_text("safe\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (project / "escape").symlink_to(outside)
    database = await get_db()
    try:
        await _session(database, "tool-session")
        service = ProjectWorkspaceService(database, managed_root=tmp_path / "managed")
        registered = await service.register_project(str(project))
        with pytest.raises(WorkspaceError, match="symbolic links"):
            await service.prepare_workspace(session_id="tool-session", project_id=registered["id"], mode=WorkspaceMode.snapshot)
        (project / "escape").unlink()
        registered = await service.register_project(str(project))
        workspace = await service.prepare_workspace(session_id="tool-session", project_id=registered["id"], mode=WorkspaceMode.snapshot)
        tools = ScopedToolService(workspace)
        with pytest.raises(WorkspaceScopeError):
            tools.read_text("../outside.txt")
        (workspace.root_path / "escape").symlink_to(outside)
        with pytest.raises(WorkspaceScopeError):
            tools.read_text("escape")
        with pytest.raises(WorkspaceError, match="destructive"):
            tools.run(["rm", "-rf", "."])
        with pytest.raises(WorkspaceError, match="destructive"):
            tools.run(["sh", "-c", "printf unsafe"])
        with pytest.raises(WorkspaceError, match="policy"):
            tools.run(["python3", "-c", "print('escape')"])
        with pytest.raises(WorkspaceScopeError):
            tools.run(["git", "-C", "/", "status"])
        monkeypatch.setattr("app.services.workspace_service.shutil.which", lambda _: None)
        with pytest.raises(WorkspaceError, match="sandbox"):
            tools.run(["pytest", "--version"])
        monkeypatch.setenv("ARGUS_TEST_SECRET", "must-not-leak")
        output = tools.run(["env"], environment={"API_TOKEN": "not-forwarded", "LANG": "C"})
        by_name = {tool.name: tool for tool in create_scoped_tools(workspace)}
        escaped = by_name["read_file"].invoke({"path": "../outside.txt"})
        searched = by_name["search_files"].invoke({"pattern": "safe", "path": "."})
    finally:
        await database.close()

    assert "API_TOKEN" not in output.stdout
    assert "ARGUS_TEST_SECRET" not in output.stdout
    assert escaped.startswith("Error:")
    assert "safe.txt" in searched


@pytest.mark.asyncio
async def test_project_code_commands_use_an_empty_root_filesystem_sandbox(temporary_sqlite_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "plain"
    project.mkdir()
    database = await get_db()
    try:
        await _session(database, "sandbox-session")
        service = ProjectWorkspaceService(database, managed_root=tmp_path / "managed")
        registered = await service.register_project(str(project))
        workspace = await service.prepare_workspace(session_id="sandbox-session", project_id=registered["id"], mode=WorkspaceMode.snapshot)
        tools = ScopedToolService(workspace)
        captured: list[str] = []

        def fake_run(argv, **kwargs):
            captured.extend(argv)
            return subprocess.CompletedProcess(argv, 0, "sandboxed", "")

        monkeypatch.setattr("app.services.workspace_service.shutil.which", lambda _: "/usr/bin/bwrap")
        monkeypatch.setattr("app.services.workspace_service.subprocess.run", fake_run)
        result = tools.run(["pytest", "--version"])
    finally:
        await database.close()

    assert result.stdout == "sandboxed"
    assert "--tmpfs" in captured and captured[captured.index("--tmpfs") + 1] == "/"
    assert "/workspace" in captured and "/home" not in captured


@pytest.mark.asyncio
async def test_descriptor_relative_write_does_not_follow_a_racing_parent_symlink(temporary_sqlite_db, tmp_path: Path) -> None:
    project = tmp_path / "plain"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    database = await get_db()
    try:
        await _session(database, "race-session")
        service = ProjectWorkspaceService(database, managed_root=tmp_path / "managed")
        registered = await service.register_project(str(project))
        workspace = await service.prepare_workspace(session_id="race-session", project_id=registered["id"], mode=WorkspaceMode.snapshot)
        racing = workspace.root_path / "racing"
        racing.mkdir()
        stop = threading.Event()

        def swap_parent() -> None:
            while not stop.is_set():
                try:
                    if racing.is_symlink():
                        racing.unlink()
                    elif racing.exists():
                        racing.rmdir()
                    racing.symlink_to(outside, target_is_directory=True)
                    racing.unlink()
                    racing.mkdir()
                except OSError:
                    pass

        thread = threading.Thread(target=swap_parent, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                try:
                    ScopedToolService(workspace).write_text("racing/inside.txt", "safe")
                except OSError:
                    pass
        finally:
            stop.set()
            thread.join(timeout=2)
    finally:
        await database.close()

    assert not (outside / "inside.txt").exists()


@pytest.mark.asyncio
async def test_writer_lock_serializes_sessions_and_recovers_expired_lease_with_audit(temporary_sqlite_db, tmp_path: Path) -> None:
    project = tmp_path / "plain"
    project.mkdir()
    database = await get_db()
    try:
        await _session(database, "first")
        await _session(database, "second")
        service = ProjectWorkspaceService(database, managed_root=tmp_path / "managed")
        registered = await service.register_project(str(project))
        first = await service.acquire_writer_lease(project_id=registered["id"], session_id="first", holder_id="builder", ttl_ms=1_000)
        await service.renew_writer_lease(first, holder_id="builder", ttl_ms=2_000)
        async with database.execute("SELECT expires_at_ms - renewed_at_ms AS remaining FROM writer_leases WHERE id = ?", (first,)) as cursor:
            assert (await cursor.fetchone())["remaining"] == 2_000
        with pytest.raises(WriterLeaseUnavailable):
            await service.acquire_writer_lease(project_id=registered["id"], session_id="second", holder_id="builder", ttl_ms=1_000)
        with pytest.raises(WriterLeaseUnavailable):
            await service.acquire_writer_lease(project_id=registered["id"], session_id="first", holder_id="other-writer", ttl_ms=1_000)
        await database.execute("UPDATE writer_leases SET expires_at_ms = acquired_at_ms + 1 WHERE id = ?", (first,))
        await database.commit()
        second = await service.acquire_writer_lease(project_id=registered["id"], session_id="second", holder_id="builder", ttl_ms=1_000)
        assert await service.release_writer_lease(second, holder_id="builder", reason="completed") is True
        reacquired = await service.acquire_writer_lease(project_id=registered["id"], session_id="second", holder_id="builder", ttl_ms=1_000)
        assert await service.release_writer_lease(reacquired, holder_id="builder", reason="completed") is True
        async with database.execute("SELECT action FROM workspace_audit WHERE session_id = 'first' ORDER BY created_at_ms") as cursor:
            actions = [row["action"] for row in await cursor.fetchall()]
    finally:
        await database.close()

    assert "writer_lease.recovered" in actions


@pytest.mark.asyncio
async def test_restart_recovery_releases_expired_leases_and_removes_unregistered_managed_workspace(temporary_sqlite_db, tmp_path: Path) -> None:
    project = tmp_path / "plain"
    project.mkdir()
    managed = tmp_path / "managed"
    orphan = managed / "interrupted-session"
    orphan.mkdir(parents=True)
    (orphan / "partial.txt").write_text("partial", encoding="utf-8")
    database = await get_db()
    try:
        await _session(database, "recovery-session")
        service = ProjectWorkspaceService(database, managed_root=managed)
        registered = await service.register_project(str(project))
        lease = await service.acquire_writer_lease(project_id=registered["id"], session_id="recovery-session", holder_id="builder")
        await database.execute("UPDATE writer_leases SET expires_at_ms = acquired_at_ms + 1 WHERE id = ?", (lease,))
        await database.commit()
        await asyncio.sleep(0.01)
        await service.recover_after_restart()
        async with database.execute("SELECT released_at_ms, release_reason FROM writer_leases WHERE id = ?", (lease,)) as cursor:
            recovered = await cursor.fetchone()
    finally:
        await database.close()

    assert not orphan.exists()
    assert recovered["released_at_ms"] is not None and recovered["release_reason"] == "expired_recovery"
