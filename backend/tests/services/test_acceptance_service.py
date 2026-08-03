from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from app.db.database import get_db
from app.db.repositories import SessionRepository
from app.schemas.project import WorkspaceMode
from app.schemas.session import ApprovalPolicy, SessionAgentInput, SessionConfigurationInput
from app.schemas.session_store import AcceptanceActionRequest
from app.schemas.session_commands import parse_session_command
from app.services.acceptance_service import AcceptanceError, AcceptanceService
from app.services.command_processor import CommandProcessor
from app.services.session_configuration_service import SessionConfigurationService
from app.services.workspace_service import ProjectWorkspaceService, ScopedToolService


async def _prepared_snapshot(database, tmp_path: Path, session_id: str = "acceptance-session"):
    source = tmp_path / "project"
    source.mkdir()
    (source / "README.md").write_text("base\n", encoding="utf-8")
    await SessionRepository(database).create_legacy_session(
        session_id=session_id, name="Acceptance", project_path=str(source), task="Review changes", role_configs=[]
    )
    workspaces = ProjectWorkspaceService(database, managed_root=tmp_path / "managed")
    registered = await workspaces.register_project(str(source))
    workspace = await workspaces.prepare_workspace(session_id=session_id, project_id=str(registered["id"]), mode=WorkspaceMode.snapshot)
    await SessionConfigurationService(database).create_initial(
        session_id=session_id,
        agents=[SessionAgentInput(id="coordinator", role="coordinator"), SessionAgentInput(id="builder", role="builder", capabilities=["workspace.write"])],
        coordinator_id="coordinator",
        configuration=SessionConfigurationInput(
            availableAgentIds=["builder"],
            approvalPolicy=ApprovalPolicy(permissionProfile="autonomous", behavior="ask_by_policy"),
            acknowledgements=["autonomous_permissions"],
        ),
        workspace_mode="snapshot", acknowledged_direct_write=False,
    )
    await database.execute("UPDATE sessions SET status = 'completed' WHERE id = ?", (session_id,))
    await database.commit()
    return source, workspace


@pytest.mark.asyncio
async def test_review_apply_is_policy_checked_idempotent_and_retains_workspace(temporary_sqlite_db, tmp_path: Path) -> None:
    database = await get_db()
    try:
        source, workspace = await _prepared_snapshot(database, tmp_path)
        ScopedToolService(workspace).write_text("README.md", "changed\n")
        service = AcceptanceService(database, managed_root=tmp_path / "managed")
        review = await service.review("acceptance-session")
        assert review["canApply"] is True
        assert review["files"] == [{"path": "README.md", "change": "modified", "additions": 1, "deletions": 1, "byteLength": 8}]
        waiting = await service.act("acceptance-session", AcceptanceActionRequest(
            commandId="apply-1", action="apply", disposition="retain", expectedOriginalChecksum=review["originalChecksum"],
        ))
        duplicate = await service.act("acceptance-session", AcceptanceActionRequest(
            commandId="apply-1", action="apply", disposition="retain", expectedOriginalChecksum=review["originalChecksum"],
        ))
        async with database.execute("SELECT id FROM approvals WHERE session_id = ? AND capability = 'original_project.write'", ("acceptance-session",)) as cursor:
            approval = await cursor.fetchone()
        await CommandProcessor(database).process("acceptance-session", parse_session_command({
            "commandId": "grant-original", "type": "approval.resolve",
            "payload": {"approvalId": approval["id"], "resolution": "grant", "grantCapabilities": ["original_project.write"], "scopeSummary": "Apply the reviewed changes to the registered original project.", "grantScope": "once"},
        }))
        response = await service.act("acceptance-session", AcceptanceActionRequest(
            commandId="apply-2", action="apply", disposition="retain", expectedOriginalChecksum=review["originalChecksum"],
        ))
    finally:
        await database.close()

    assert waiting["state"] == "waiting_approval"
    assert duplicate == waiting
    assert response["state"] == "applied"
    assert source.joinpath("README.md").read_text(encoding="utf-8") == "changed\n"
    assert workspace.root_path.exists()


@pytest.mark.asyncio
async def test_drift_blocks_apply_without_writing_and_reject_cleanup_is_explicit(temporary_sqlite_db, tmp_path: Path) -> None:
    database = await get_db()
    try:
        source, workspace = await _prepared_snapshot(database, tmp_path, "drift-session")
        ScopedToolService(workspace).write_text("README.md", "isolated\n")
        source.joinpath("README.md").write_text("user edit\n", encoding="utf-8")
        service = AcceptanceService(database, managed_root=tmp_path / "managed")
        review = await service.review("drift-session")
        blocked = await service.act("drift-session", AcceptanceActionRequest(
            commandId="apply-drift", action="apply", disposition="retain", expectedOriginalChecksum=review["originalChecksum"],
        ))
        rejected = await service.act("drift-session", AcceptanceActionRequest(
            commandId="reject-clean", action="reject", disposition="cleanup",
        ))
    finally:
        await database.close()

    assert review["drifted"] is True
    assert blocked["state"] == "drifted"
    assert source.joinpath("README.md").read_text(encoding="utf-8") == "user edit\n"
    assert rejected["state"] == "rejected"
    assert not workspace.root_path.exists()


@pytest.mark.asyncio
async def test_follow_up_starts_a_fresh_isolated_session_from_snapshots(temporary_sqlite_db, tmp_path: Path) -> None:
    database = await get_db()
    try:
        _, workspace = await _prepared_snapshot(database, tmp_path, "follow-up-source")
        service = AcceptanceService(database, managed_root=tmp_path / "managed")
        result = await service.act("follow-up-source", AcceptanceActionRequest(
            commandId="follow-up-1", action="follow_up", disposition="retain", followUpGoal="Verify the retained review result.",
        ))
        async with database.execute("SELECT id, status FROM sessions WHERE name LIKE 'Follow-up:%'") as cursor:
            follow_up = await cursor.fetchone()
        async with database.execute("SELECT root_path FROM workspaces WHERE session_id = ?", (follow_up["id"],)) as cursor:
            follow_up_workspace = await cursor.fetchone()
    finally:
        await database.close()

    assert result["state"] == "follow_up_started"
    assert follow_up["status"] == "setup"
    assert Path(follow_up_workspace["root_path"]).exists()
    assert workspace.root_path.exists()


@pytest.mark.asyncio
async def test_nonterminal_cleanup_and_sensitive_patch_export_fail_closed(temporary_sqlite_db, tmp_path: Path) -> None:
    database = await get_db()
    try:
        _, workspace = await _prepared_snapshot(database, tmp_path, "safe-export")
        service = AcceptanceService(database, managed_root=tmp_path / "managed")
        await database.execute("UPDATE sessions SET status = 'running' WHERE id = 'safe-export'")
        await database.commit()
        with pytest.raises(AcceptanceError, match="Finish"):
            await service.act("safe-export", AcceptanceActionRequest(commandId="unsafe-clean", action="reject", disposition="cleanup"))
        assert workspace.root_path.exists()
        await database.execute("UPDATE sessions SET status = 'completed' WHERE id = 'safe-export'")
        await database.commit()
        ScopedToolService(workspace).write_text(".env", "API_KEY=sk-abcdefghijklmnop\n")
        review = await service.review("safe-export")
        with pytest.raises(AcceptanceError, match="binary, oversized, or unsupported"):
            await service.patch("safe-export")
    finally:
        await database.close()

    assert review["patchAvailable"] is False


@pytest.mark.asyncio
async def test_worktree_review_includes_untracked_file_without_touching_original(temporary_sqlite_db, tmp_path: Path) -> None:
    project = tmp_path / "git-project"
    project.mkdir()
    for args in (("init",), ("config", "user.email", "argus@example.invalid"), ("config", "user.name", "Argus")):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True, text=True)
    (project / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=project, check=True, capture_output=True, text=True)
    database = await get_db()
    try:
        await SessionRepository(database).create_legacy_session(session_id="worktree-review", name="Worktree", project_path=str(project), task="Review", role_configs=[])
        workspaces = ProjectWorkspaceService(database, managed_root=tmp_path / "managed")
        registered = await workspaces.register_project(str(project))
        workspace = await workspaces.prepare_workspace(session_id="worktree-review", project_id=str(registered["id"]), mode=WorkspaceMode.worktree)
        await SessionConfigurationService(database).create_initial(
            session_id="worktree-review", agents=[SessionAgentInput(id="coordinator", role="coordinator")], coordinator_id="coordinator",
            configuration=SessionConfigurationInput(), workspace_mode="worktree", acknowledged_direct_write=False,
        )
        await database.execute("UPDATE sessions SET status = 'completed' WHERE id = 'worktree-review'")
        await database.commit()
        ScopedToolService(workspace).write_text("added.txt", "isolated\n")
        review = await AcceptanceService(database, managed_root=tmp_path / "managed").review("worktree-review")
    finally:
        await database.close()

    assert any(item["path"] == "added.txt" and item["change"] == "added" for item in review["files"])
    assert not (project / "added.txt").exists()


@pytest.mark.asyncio
async def test_apply_patch_supports_added_and_deleted_text_files(temporary_sqlite_db, tmp_path: Path) -> None:
    database = await get_db()
    try:
        source, workspace = await _prepared_snapshot(database, tmp_path, "add-delete")
        (workspace.root_path / "README.md").unlink()
        ScopedToolService(workspace).write_text("new.txt", "new isolated file\n")
        service = AcceptanceService(database, managed_root=tmp_path / "managed")
        review = await service.review("add-delete")
        assert {item["change"] for item in review["files"]} == {"added", "deleted"}
        waiting = await service.act("add-delete", AcceptanceActionRequest(commandId="add-delete-ask", action="apply", disposition="retain", expectedOriginalChecksum=review["originalChecksum"]))
        async with database.execute("SELECT id FROM approvals WHERE session_id = ? AND capability = 'original_project.write'", ("add-delete",)) as cursor:
            approval = await cursor.fetchone()
        await CommandProcessor(database).process("add-delete", parse_session_command({
            "commandId": "add-delete-grant", "type": "approval.resolve",
            "payload": {"approvalId": approval["id"], "resolution": "grant", "grantCapabilities": ["original_project.write"], "scopeSummary": "Apply reviewed changes to the original project.", "grantScope": "once"},
        }))
        applied = await service.act("add-delete", AcceptanceActionRequest(commandId="add-delete-apply", action="apply", disposition="retain", expectedOriginalChecksum=review["originalChecksum"]))
    finally:
        await database.close()

    assert waiting["state"] == "waiting_approval"
    assert applied["state"] == "applied"
    assert not source.joinpath("README.md").exists()
    assert source.joinpath("new.txt").read_text(encoding="utf-8") == "new isolated file\n"
