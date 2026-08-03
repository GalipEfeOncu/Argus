"""Bounded, policy-checked review and acceptance of isolated session work."""

from __future__ import annotations

import asyncio
import difflib
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Literal
import uuid

import aiosqlite

from app.db.database import transaction
from app.db.repositories import EventRepository, _SENSITIVE_VALUE, _now_ms
from app.schemas.project import WorkspaceMode
from app.schemas.session import SessionAgentInput, SessionConfigurationInput
from app.schemas.session_store import AcceptanceActionRequest
from app.services.approval_grant_service import ApprovalGrantService
from app.services.gate_engine import GateEngine
from app.services.worker_fence import session_mutation_fence
from app.services.workspace_service import ProjectWorkspaceService, WorkspaceError, _workspace_checksum
from app.services.session_configuration_service import SessionConfigurationService
from app.db.repositories import SessionRepository


_MAX_PATCH_BYTES = 2_000_000
_MAX_FILE_BYTES = 512_000
_MAX_TREE_FILES = 1_000


class AcceptanceError(ValueError):
    """A stable, user-safe acceptance workflow failure."""


def _relative_files(root: Path) -> dict[str, bytes]:
    """Read a bounded, symlink-free workspace tree without `.git` metadata."""

    result: dict[str, bytes] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(name for name in directories if name != ".git")
        for name in sorted(files):
            path = current_path / name
            # A linked git worktree stores its administrative pointer as a
            # `.git` *file*. It is not project content and must never enter a
            # review tree or generated patch.
            if path.relative_to(root).as_posix() == ".git":
                continue
            if path.is_symlink() or not path.is_file():
                raise AcceptanceError("The review workspace contains an unsupported symbolic link or special file.")
            relative = path.relative_to(root).as_posix()
            if relative == ".git" or ".." in Path(relative).parts or any(character in relative for character in ("\0", "\n", "\r")):
                raise AcceptanceError("The review workspace contains an unsafe path.")
            data = path.read_bytes()
            result[relative] = data
            if len(result) > _MAX_TREE_FILES:
                raise AcceptanceError("The review contains too many files to safely render at once.")
    return result


def _text(value: bytes) -> str | None:
    if len(value) > _MAX_FILE_BYTES or b"\0" in value:
        return None
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _sensitive_path(path: str) -> bool:
    name = Path(path).name.lower()
    return (
        name == ".env" or name.startswith(".env.") or name in {".netrc", ".npmrc", "id_ed25519", "id_rsa"}
        or name.endswith((".pem", ".key", ".p12", ".pfx"))
        or any(marker in name for marker in ("credential", "secret", "private_key"))
    )


def _file_changes(base: dict[str, bytes], current: dict[str, bytes]) -> tuple[list[dict[str, object]], str, bool]:
    """Produce metadata and a conservative text-only unified patch."""

    entries: list[dict[str, object]] = []
    chunks: list[str] = []
    patchable = True
    for path in sorted(set(base) | set(current)):
        before, after = base.get(path), current.get(path)
        if before == after:
            continue
        before_text = None if before is None else _text(before)
        after_text = None if after is None else _text(after)
        if _sensitive_path(path) or (before_text is not None and (_SENSITIVE_VALUE.search(before_text) or "-----BEGIN " in before_text and " PRIVATE KEY-----" in before_text)) or (after_text is not None and (_SENSITIVE_VALUE.search(after_text) or "-----BEGIN " in after_text and " PRIVATE KEY-----" in after_text)):
            entries.append({"path": path, "change": "binary", "additions": 0, "deletions": 0, "byteLength": len(after or before or b"")})
            patchable = False
            continue
        if (before_text is None and before is not None) or (after_text is None and after is not None):
            entries.append({"path": path, "change": "binary", "additions": 0, "deletions": 0, "byteLength": len(after or before or b"")})
            patchable = False
            continue
        old_lines = [] if before_text is None else before_text.splitlines(keepends=True)
        new_lines = [] if after_text is None else after_text.splitlines(keepends=True)
        additions = sum(1 for line in difflib.ndiff(old_lines, new_lines) if line.startswith("+ "))
        deletions = sum(1 for line in difflib.ndiff(old_lines, new_lines) if line.startswith("- "))
        kind: Literal["added", "modified", "deleted"] = "added" if before is None else "deleted" if after is None else "modified"
        entries.append({"path": path, "change": kind, "additions": additions, "deletions": deletions, "byteLength": len(after or before or b"")})
        chunks.append(f"diff --git a/{path} b/{path}\n")
        if before is None:
            chunks.append("new file mode 100644\n")
        elif after is None:
            chunks.append("deleted file mode 100644\n")
        chunks.extend(difflib.unified_diff(
            old_lines, new_lines, fromfile="/dev/null" if before is None else f"a/{path}",
            tofile="/dev/null" if after is None else f"b/{path}", lineterm="\n",
        ))
    patch = "".join(chunks)
    if len(patch.encode()) > _MAX_PATCH_BYTES:
        patchable = False
        patch = ""
    return entries, patch, patchable


class AcceptanceService:
    def __init__(self, db: aiosqlite.Connection, *, managed_root: Path) -> None:
        self._db = db
        self._workspaces = ProjectWorkspaceService(db, managed_root=managed_root)
        self._events = EventRepository(db)

    async def review(self, session_id: str) -> dict[str, object]:
        await self._require_terminal(session_id)
        workspace = await self._workspaces.workspace_for_session(session_id)
        source = await self._source_path(workspace.project_id)
        current_original = await asyncio.to_thread(_workspace_checksum, source)
        base, current = await asyncio.to_thread(self._trees_for_workspace, workspace)
        files, patch, patchable = _file_changes(base, current)
        artifacts = await self._events.page_artifact_summaries(session_id, limit=100)
        gates = await GateEngine(self._db).states(session_id)
        limits, usage, coordinator_summary = await self._timeline_summary(session_id)
        latest = await self._latest_action(session_id)
        drifted = workspace.original_revision_checksum is None or current_original != workspace.original_revision_checksum
        can_apply = workspace.mode is not WorkspaceMode.direct_write and patchable and bool(patch) and not drifted
        return {
            "sessionId": session_id, "workspaceMode": workspace.mode.value, "workspaceChecksum": workspace.revision_checksum,
            "originalChecksum": workspace.original_revision_checksum, "currentOriginalChecksum": current_original,
            "drifted": drifted, "canApply": can_apply, "patchAvailable": patchable and bool(patch), "files": files,
            "artifacts": list(artifacts.items),
            "gates": [{"id": state.rule["id"], "role": state.rule["role"], "status": state.status, "evidenceCount": state.valid_completions} for state in gates],
            "unmetGates": [f"{state.rule['role']}: {state.status}" for state in gates if state.status == "pending"],
            "limits": limits, "usage": usage, "coordinatorSummary": coordinator_summary, "latestAction": latest,
        }

    async def patch(self, session_id: str) -> dict[str, str]:
        await self._require_terminal(session_id)
        workspace = await self._workspaces.workspace_for_session(session_id)
        if workspace.mode is WorkspaceMode.direct_write:
            raise AcceptanceError("Direct-write sessions have no isolated patch to export.")
        base, current = await asyncio.to_thread(self._trees_for_workspace, workspace)
        _, patch, patchable = _file_changes(base, current)
        if not patchable:
            raise AcceptanceError("The isolated changes include binary, oversized, or unsupported files; retain the workspace for manual review.")
        return {"patch": patch, "checksum": sha256(patch.encode()).hexdigest()}

    async def act(self, session_id: str, request: AcceptanceActionRequest) -> dict[str, object]:
        existing = await self._action_for_command(session_id, request.command_id)
        if existing is not None:
            return existing
        await self._require_terminal(session_id)
        if await self._active_runtime_work(session_id):
            raise AcceptanceError("Acceptance actions are unavailable while work, a tool, provider operation, or writer lease is active.")
        if request.action == "apply":
            return await self._apply(session_id, request)
        return await self._non_mutating_action(session_id, request)

    async def _apply(self, session_id: str, request: AcceptanceActionRequest) -> dict[str, object]:
        workspace = await self._workspaces.workspace_for_session(session_id)
        if workspace.mode is WorkspaceMode.direct_write:
            return await self._record_action(session_id, request, "denied", "Direct-write sessions are already applied and cannot be applied again.")
        if request.expected_original_checksum is None or request.expected_original_checksum != workspace.original_revision_checksum:
            return await self._record_action(session_id, request, "denied", "Refresh the review before applying: the original-project baseline is missing or stale.")
        review = await self.review(session_id)
        if bool(review["drifted"]):
            return await self._record_action(session_id, request, "drifted", "The original project changed after this session started. No files were written; export the patch or retain the workspace to resolve the conflict safely.")
        if not bool(review["canApply"]):
            return await self._record_action(session_id, request, "denied", "This review cannot be applied automatically. Export the patch or retain the workspace for manual review.")
        authority = await ApprovalGrantService(self._db).evaluate(session_id, capability="original_project.write", scope_path=".", operation_class="mutating")
        if authority.outcome == "ask":
            async with transaction(self._db):
                await ApprovalGrantService(self._db).request_in_transaction(
                    session_id, capability="original_project.write", scope_path=".", scope_summary="Apply the reviewed isolated changes to the registered original project.", operation_class="mutating",
                )
            return await self._record_action(session_id, request, "waiting_approval", "Approval is required before applying the isolated changes to the original project.")
        if authority.outcome != "allow":
            return await self._record_action(session_id, request, "denied", "Current workspace policy does not allow applying these changes.")
        # Consume a one-time human grant only at the last possible point before
        # the filesystem operation; a lost response can never trigger replay.
        async with transaction(self._db):
            consumed = await ApprovalGrantService(self._db).evaluate(session_id, capability="original_project.write", scope_path=".", operation_class="mutating", consume_once=True)
        if consumed.outcome != "allow":
            return await self._record_action(session_id, request, "denied", "The approval is no longer active. Refresh and request a new approval.")
        action = await self._record_action(session_id, request, "applying", "Applying the reviewed isolated changes.")
        holder = f"acceptance:{request.command_id}"
        lease_id: str | None = None
        try:
            lease_id = await self._workspaces.acquire_writer_lease(project_id=workspace.project_id, session_id=session_id, holder_id=holder)
            async with session_mutation_fence.mutation(session_id):
                source = await self._source_path(workspace.project_id)
                observed = await asyncio.to_thread(_workspace_checksum, source)
                if observed != workspace.original_revision_checksum:
                    return await self._finish_action(action["id"], "drifted", "The original project changed immediately before apply. No files were written.", observed)
                exported = await self.patch(session_id)
                await asyncio.to_thread(self._apply_patch, source, exported["patch"])
            if request.disposition == "cleanup":
                try:
                    await self._workspaces.cleanup_workspace(session_id)
                except (WorkspaceError, OSError):
                    return await self._finish_action(action["id"], "applied", "Reviewed changes were applied, but workspace cleanup failed. The isolated workspace was retained for safe manual cleanup.", observed)
            return await self._finish_action(action["id"], "applied", "Reviewed changes were applied to the original project." + (" The isolated workspace was cleaned up." if request.disposition == "cleanup" else " The isolated workspace was retained."), observed)
        except (AcceptanceError, WorkspaceError, OSError, subprocess.SubprocessError) as error:
            return await self._finish_action(action["id"], "failed", f"Apply did not complete: {str(error)[:500]}")
        finally:
            if lease_id is not None:
                await self._workspaces.release_writer_lease(lease_id, holder_id=holder, reason="acceptance_finished")

    async def _non_mutating_action(self, session_id: str, request: AcceptanceActionRequest) -> dict[str, object]:
        if request.action == "export":
            await self.patch(session_id)
            return await self._record_action(session_id, request, "exported", "Patch export is ready. The isolated workspace was retained for safety.")
        if request.action == "reject":
            if request.disposition == "cleanup":
                await self._workspaces.cleanup_workspace(session_id)
                return await self._record_action(session_id, request, "rejected", "Changes were rejected and the isolated workspace was cleaned up.")
            return await self._record_action(session_id, request, "rejected", "Changes were rejected and the isolated workspace was retained.")
        if request.follow_up_goal is None:
            raise AcceptanceError("A follow-up goal is required.")
        follow_up_id = await self._start_follow_up_session(session_id, request.follow_up_goal)
        if request.disposition == "cleanup":
            try:
                await self._workspaces.cleanup_workspace(session_id)
            except (WorkspaceError, OSError):
                return await self._record_action(session_id, request, "follow_up_started", f"Started follow-up session {follow_up_id}; source workspace cleanup failed and it was retained.")
        return await self._record_action(session_id, request, "follow_up_started", f"Started follow-up session {follow_up_id} for: {request.follow_up_goal}")

    async def _start_follow_up_session(self, session_id: str, goal: str) -> str:
        """Fork approved configuration into a fresh isolated session, never a raw workspace copy."""

        workspace = await self._workspaces.workspace_for_session(session_id)
        if workspace.mode is WorkspaceMode.direct_write:
            raise AcceptanceError("Direct-write sessions cannot create a follow-up automatically; start a new reviewed session instead.")
        async with self._db.execute("SELECT name FROM sessions WHERE id = ?", (session_id,)) as cursor:
            session = await cursor.fetchone()
        if session is None:
            raise AcceptanceError("Session not found.")
        snapshot = await SessionConfigurationService(self._db).current(session_id)
        async with self._db.execute("SELECT snapshot_json FROM session_agents WHERE session_id = ? ORDER BY created_at_ms, id", (session_id,)) as cursor:
            agent_rows = await cursor.fetchall()
        import json
        agents = [SessionAgentInput.model_validate(json.loads(row["snapshot_json"])) for row in agent_rows]
        coordinator = next((agent for agent in agents if agent.role == "coordinator"), None)
        if coordinator is None:
            raise AcceptanceError("The source session has no Coordinator snapshot.")
        source_ids = {str(agent["id"]): str(agent["sourceAgentId"]) for agent in snapshot.agent_snapshots}
        configuration = SessionConfigurationInput.model_validate({
            "availableAgentIds": [source_ids[item] for item in snapshot.available_agent_ids],
            "requiredRoleRules": snapshot.required_role_rules,
            "executionLimits": snapshot.execution_limits,
            "approvalPolicy": snapshot.approval_policy,
            "workspacePolicy": snapshot.workspace_policy,
            "acknowledgements": snapshot.acknowledgements,
        })
        follow_up_id = str(uuid.uuid4())
        await SessionRepository(self._db).create_legacy_session(
            session_id=follow_up_id, name=f"Follow-up: {session['name']}", project_path=str(await self._source_path(workspace.project_id)),
            task=goal, role_configs=[], project_id=workspace.project_id,
        )
        try:
            next_workspace = await self._workspaces.prepare_workspace(
                session_id=follow_up_id, project_id=workspace.project_id, mode=workspace.mode, acknowledged_direct_write=False,
            )
            await SessionRepository(self._db).set_workspace_path(follow_up_id, str(next_workspace.root_path))
            async with transaction(self._db):
                await SessionConfigurationService(self._db).create_initial(
                    session_id=follow_up_id, agents=agents, coordinator_id=coordinator.id, configuration=configuration,
                    workspace_mode=workspace.mode.value, acknowledged_direct_write=False,
                )
        except BaseException:
            try:
                await self._workspaces.cleanup_workspace(follow_up_id)
            except WorkspaceError:
                pass
            await SessionRepository(self._db).discard_unstarted_session(follow_up_id)
            raise
        return follow_up_id

    async def _record_action(self, session_id: str, request: AcceptanceActionRequest, state: str, summary: str) -> dict[str, object]:
        action_id = f"acceptance_{uuid.uuid4().hex}"
        now = _now_ms()
        terminal = state not in {"pending", "waiting_approval", "applying"}
        async with transaction(self._db):
            await self._db.execute(
                """INSERT INTO acceptance_actions (id, session_id, command_id, action, disposition, state, expected_original_checksum, summary, created_at_ms, completed_at_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (action_id, session_id, request.command_id, request.action, request.disposition, state, request.expected_original_checksum, summary, now, now if terminal else None),
            )
        await self._append_action_message(session_id, request.command_id, summary)
        return {"id": action_id, "action": request.action, "disposition": request.disposition, "state": state, "summary": summary, "createdAtMs": now, "completedAtMs": now if terminal else None}

    async def _finish_action(self, action_id: str, state: str, summary: str, observed: str | None = None) -> dict[str, object]:
        now = _now_ms()
        async with transaction(self._db):
            async with self._db.execute("SELECT * FROM acceptance_actions WHERE id = ?", (action_id,)) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise AcceptanceError("Acceptance action is missing.")
            await self._db.execute("UPDATE acceptance_actions SET state = ?, summary = ?, observed_original_checksum = ?, completed_at_ms = ? WHERE id = ?", (state, summary, observed, now, action_id))
        await self._append_action_message(str(row["session_id"]), str(row["command_id"]), summary)
        return {"id": action_id, "action": row["action"], "disposition": row["disposition"], "state": state, "summary": summary, "createdAtMs": row["created_at_ms"], "completedAtMs": now}

    async def _append_action_message(self, session_id: str, command_id: str, summary: str) -> None:
        await self._events.append(event_id=f"acceptance_event_{uuid.uuid4().hex}", session_id=session_id, event_type="message.created", actor_id="human", correlation_id=command_id, command_id=None, timestamp_ms=_now_ms(), payload={"messageId": f"acceptance_message_{uuid.uuid4().hex}", "authorId": "human", "authorKind": "human", "content": summary, "mentionIds": [], "streaming": False})

    async def _action_for_command(self, session_id: str, command_id: str) -> dict[str, object] | None:
        async with self._db.execute("SELECT * FROM acceptance_actions WHERE session_id = ? AND command_id = ?", (session_id, command_id)) as cursor:
            row = await cursor.fetchone()
        return None if row is None else self._action_value(row)

    async def _latest_action(self, session_id: str) -> dict[str, object] | None:
        async with self._db.execute("SELECT * FROM acceptance_actions WHERE session_id = ? ORDER BY created_at_ms DESC, id DESC LIMIT 1", (session_id,)) as cursor:
            row = await cursor.fetchone()
        return None if row is None else self._action_value(row)

    @staticmethod
    def _action_value(row: aiosqlite.Row) -> dict[str, object]:
        return {"id": row["id"], "action": row["action"], "disposition": row["disposition"], "state": row["state"], "summary": row["summary"], "createdAtMs": row["created_at_ms"], "completedAtMs": row["completed_at_ms"]}

    async def _source_path(self, project_id: str) -> Path:
        async with self._db.execute("SELECT canonical_path FROM projects WHERE id = ?", (project_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise AcceptanceError("Original project is no longer registered.")
        return Path(row["canonical_path"])

    @staticmethod
    def _trees_for_workspace(workspace) -> tuple[dict[str, bytes], dict[str, bytes]]:
        current = _relative_files(workspace.root_path)
        if workspace.mode is WorkspaceMode.snapshot:
            if workspace.baseline_path is None or not workspace.baseline_path.is_dir():
                raise AcceptanceError("The snapshot baseline is unavailable; automatic apply is blocked.")
            return _relative_files(workspace.baseline_path), current
        if workspace.mode is WorkspaceMode.worktree:
            result = subprocess.run(["git", "ls-tree", "-r", "-z", "--name-only", "HEAD"], cwd=workspace.root_path, capture_output=True, check=False)
            if result.returncode != 0:
                raise AcceptanceError("The worktree baseline is unavailable; automatic apply is blocked.")
            base: dict[str, bytes] = {}
            for raw in result.stdout.split(b"\0"):
                if not raw:
                    continue
                path = raw.decode("utf-8", "strict")
                if ".." in Path(path).parts or path.startswith("/"):
                    raise AcceptanceError("The worktree baseline contains an unsafe path.")
                content = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=workspace.root_path, capture_output=True, check=False)
                if content.returncode != 0:
                    raise AcceptanceError("The worktree baseline could not be read safely.")
                base[path] = content.stdout
            return base, current
        return current, current

    @staticmethod
    def _apply_patch(source: Path, patch: str) -> None:
        if not patch:
            raise AcceptanceError("There are no text changes to apply.")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".patch", delete=False) as handle:
            handle.write(patch)
            patch_path = Path(handle.name)
        try:
            for args in (("git", "apply", "--check", "--whitespace=nowarn", str(patch_path)), ("git", "apply", "--whitespace=nowarn", str(patch_path))):
                result = subprocess.run(args, cwd=source, capture_output=True, text=True, check=False, timeout=30)
                if result.returncode != 0:
                    raise AcceptanceError("The patch no longer applies cleanly to the original project.")
        finally:
            patch_path.unlink(missing_ok=True)

    async def _require_terminal(self, session_id: str) -> None:
        async with self._db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise AcceptanceError("Session not found.")
        if row["status"] not in {"completed", "completed_partial"}:
            raise AcceptanceError("Finish or explicitly accept a partial session before applying its changes.")
        if row["status"] == "completed_partial":
            async with self._db.execute(
                """SELECT 1 FROM events WHERE session_id = ? AND event_type = 'decision.recorded'
                   AND actor_id = 'human' AND json_extract(payload_json, '$.choice') = 'deliver_partial' LIMIT 1""",
                (session_id,),
            ) as cursor:
                if await cursor.fetchone() is None:
                    raise AcceptanceError("A partial result needs an explicit human acceptance before review actions are available.")

    async def _active_runtime_work(self, session_id: str) -> bool:
        checks = (
            ("SELECT 1 FROM assignments WHERE session_id = ? AND state IN ('created', 'running') LIMIT 1",),
            ("SELECT 1 FROM tool_executions WHERE session_id = ? AND exit_state IN ('requested', 'running') LIMIT 1",),
            ("SELECT 1 FROM provider_operations WHERE session_id = ? AND state IN ('pending', 'running') LIMIT 1",),
            ("SELECT 1 FROM writer_leases WHERE session_id = ? AND released_at_ms IS NULL LIMIT 1",),
        )
        for (query,) in checks:
            async with self._db.execute(query, (session_id,)) as cursor:
                if await cursor.fetchone() is not None:
                    return True
        return False

    async def _timeline_summary(self, session_id: str) -> tuple[list[dict[str, object]], dict[str, object], str | None]:
        events = await self._events.list_for_session(session_id)
        limits = [event.payload for event in events if event.event_type in {"limit.warning", "limit.reached"}][-100:]
        usage = {"inputTokens": 0, "outputTokens": 0, "normalizedCost": 0.0, "durationMs": 0}
        cost_known = True
        coordinator_summary: str | None = None
        for event in events:
            if event.event_type == "usage.updated":
                usage["inputTokens"] += int(event.payload.get("inputTokens", 0))
                usage["outputTokens"] += int(event.payload.get("outputTokens", 0))
                usage["durationMs"] += int(event.payload.get("durationMs", 0))
                cost = event.payload.get("normalizedCost")
                if isinstance(cost, (int, float)):
                    usage["normalizedCost"] += float(cost)
                else:
                    cost_known = False
            if event.event_type == "message.created" and event.payload.get("authorKind") == "coordinator":
                content = event.payload.get("content")
                if isinstance(content, str):
                    coordinator_summary = content[:4000]
        if not cost_known:
            usage["normalizedCost"] = None
        return limits, usage, coordinator_summary
