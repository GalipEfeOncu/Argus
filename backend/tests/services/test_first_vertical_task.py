"""End-to-end acceptance coverage for Roadmap Phase 3.4."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
import uuid

from fastapi.testclient import TestClient
import pytest

from app.api import websocket as websocket_api
from app.config import settings
from app.db.database import get_db, transaction
from app.db.repositories import EventRepository, SessionRepository
from app.main import app
from app.providers.protocol import ProviderRequest, StructuredOutput
from app.providers.scripted import ScriptedProvider
from app.schemas.project import WorkspaceMode
from app.schemas.session import ApprovalPolicy, RequiredRoleRule, SessionAgentInput, SessionConfigurationInput
from app.services.first_vertical_task import FirstVerticalTaskRunner
from app.services.coordinator_cycle import CoordinatorCycle
from app.services.session_configuration_service import SessionConfigurationService
from app.services.workspace_service import ProjectWorkspaceService


def _receive_type(socket, event_type: str) -> dict[str, object]:
    for _ in range(20):
        value = socket.receive_json()
        if value["type"] == event_type:
            return value
    raise AssertionError(f"Did not receive {event_type}")


def _receive_status(socket, status: str) -> dict[str, object]:
    for _ in range(20):
        value = _receive_type(socket, "session.status_changed")
        if value["payload"]["status"] == status:
            return value
    raise AssertionError(f"Did not receive status {status}")


def _create_request(
    project: Path,
    *,
    require_review: bool = False,
    permission_profile: str = "balanced",
    approval_behavior: str = "ask_by_policy",
    preauthorized_capabilities: list[str] | None = None,
) -> dict[str, object]:
    agents: list[dict[str, object]] = [
        {"id": "coordinator", "role": "coordinator"},
        {"id": "builder", "role": "builder", "capabilities": ["workspace.write"]},
    ]
    if require_review:
        agents.append({"id": "reviewer", "role": "reviewer", "capabilities": ["workspace.read"]})
    configuration: dict[str, object] = {
        "availableAgentIds": [agent["id"] for agent in agents if agent["id"] != "coordinator"],
        "approvalPolicy": {
            "permissionProfile": permission_profile,
            "behavior": approval_behavior,
            "preauthorizedCapabilities": preauthorized_capabilities or [],
        },
        "workspacePolicy": {"mode": "snapshot"},
    }
    if permission_profile == "autonomous":
        configuration["acknowledgements"] = ["autonomous_permissions"]
    if require_review:
        configuration["requiredRoleRules"] = [{
            "id": "review", "role": "reviewer", "applicability": "when_changes", "successEvidence": "approved_review",
        }]
    return {
        "projectPath": str(project), "goal": "Create a reviewable isolated file.",
        "coordinatorAgentId": "coordinator",
        "agents": agents, "configuration": configuration,
        "workspaceMode": "snapshot", "acknowledgeDirectWrite": False,
    }


async def _events(session_id: str) -> list[object]:
    database = await get_db()
    try:
        return await EventRepository(database).list_for_session(session_id)
    finally:
        await database.close()


async def _preauthorized_runner_session(
    database, project: Path, *, tool_allowlist: list[str], model_binding: dict[str, str] | None = None,
    provider_resolver=None, require_review: bool = False,
) -> tuple[str, FirstVerticalTaskRunner]:
    session_id = str(uuid.uuid4())
    workspaces = ProjectWorkspaceService(
        database, managed_root=Path(settings.db_path).parent / "workspaces",
    )
    registered = await workspaces.register_project(str(project))
    await SessionRepository(database).create_legacy_session(
        session_id=session_id, name="Pre-authorized task", project_path=registered["canonicalPath"],
        task="Complete the isolated task.", role_configs=[], project_id=str(registered["id"]),
    )
    workspace = await workspaces.prepare_workspace(
        session_id=session_id, project_id=str(registered["id"]), mode=WorkspaceMode.snapshot,
        acknowledged_direct_write=False,
    )
    await SessionRepository(database).set_workspace_path(session_id, str(workspace.root_path))
    async with transaction(database):
        await SessionConfigurationService(database).create_initial(
            session_id=session_id,
            agents=[
                SessionAgentInput.model_validate({"id": "coordinator", "role": "coordinator", **({"modelBinding": model_binding} if model_binding is not None else {})}),
                SessionAgentInput.model_validate({
                    "id": "builder", "role": "builder", "capabilities": ["workspace.write"],
                    "toolAllowlist": tool_allowlist,
                }),
            ] + ([SessionAgentInput.model_validate({"id": "reviewer", "role": "reviewer", "capabilities": ["workspace.read"], "toolAllowlist": ["read_file"]})] if require_review else []),
            coordinator_id="coordinator",
            configuration=SessionConfigurationInput(
                availableAgentIds=["builder", "reviewer"] if require_review else ["builder"],
                approvalPolicy=ApprovalPolicy(
                    permissionProfile="autonomous", behavior="preauthorize_session",
                    preauthorizedCapabilities=["workspace.write"],
                ),
                acknowledgements=["autonomous_permissions"],
                requiredRoleRules=[RequiredRoleRule(id="review", role="reviewer", applicability="when_changes", successEvidence="approved_review")] if require_review else [],
            ),
            workspace_mode="snapshot", acknowledged_direct_write=False,
        )
    await SessionRepository(database).set_status(session_id, "preparing")
    return session_id, FirstVerticalTaskRunner(
        database, managed_root=Path(settings.db_path).parent / "workspaces", provider_resolver=provider_resolver,
    )


def test_first_vertical_task_is_replayable_isolated_and_reviewable(temporary_sqlite_db, tmp_path: Path) -> None:
    project = tmp_path / "fake-project"
    project.mkdir()
    original = project / "original.txt"
    original.write_text("The selected project must not change.\n", encoding="utf-8")

    with TestClient(app) as client:
        created = client.post("/sessions/", json=_create_request(project))
        assert created.status_code == 200
        session_id = created.json()["id"]
        with client.websocket_connect(f"/ws/sessions/{session_id}?after_sequence=0") as socket:
            assert socket.receive_json()["type"] == "session.snapshot"
            socket.send_json({"commandId": "start", "type": "session.start", "payload": {}})
            assert socket.receive_json()["payload"]["status"] == "preparing"

        # A human correction is durable even while the session is waiting for a
        # scoped grant, and its WebSocket outcome is correlated to the command.
        with client.websocket_connect(f"/ws/sessions/{session_id}?after_sequence=1") as socket:
            assert socket.receive_json()["type"] == "session.snapshot"
            replayed = socket.receive_json()
            assert replayed["type"] == "approval.requested"
            approval_id = replayed["payload"]["approvalId"]
            socket.send_json({"commandId": "correction", "type": "message.send", "payload": {"content": "Keep the original project unchanged."}})
            correction = _receive_type(socket, "message.created")
            assert correction["type"] == "message.created"
            assert correction["correlationId"] == "correction"
            socket.send_json({
                "commandId": "grant-write", "type": "approval.resolve",
                "payload": {"approvalId": approval_id, "resolution": "grant", "grantCapabilities": ["workspace.write"],
                            "scopeSummary": "Only the isolated session workspace."},
            })
            assert _receive_type(socket, "approval.resolved")["type"] == "approval.resolved"
            assert _receive_type(socket, "session.status_changed")["payload"]["status"] == "running"
            completed = _receive_type(socket, "session.status_changed")
            while completed["payload"]["status"] != "completed":
                completed = _receive_type(socket, "session.status_changed")

        events = asyncio.run(_events(session_id))
        artifact_id = next(event.payload["artifactId"] for event in events if event.event_type == "artifact.diff_updated")
        assert original.read_text(encoding="utf-8") == "The selected project must not change.\n"
        assert {event.event_type for event in events} >= {
            "approval.requested", "approval.resolved", "assignment.proposed", "assignment.created",
            "assignment.started", "tool.requested", "tool.completed", "artifact.diff_updated",
            "assignment.completed", "session.status_changed",
        }
        assert any(event.event_type == "artifact.diff_updated" and event.payload["artifactId"] == artifact_id for event in events)

        last_sequence = events[-1].sequence
        with client.websocket_connect(f"/ws/sessions/{session_id}?after_sequence={last_sequence - 2}") as socket:
            snapshot = socket.receive_json()
            assert snapshot["type"] == "session.snapshot"
            replay = [socket.receive_json(), socket.receive_json()]

    assert [event["sequence"] for event in replay] == [last_sequence - 1, last_sequence]
    assert replay[-1]["payload"]["status"] == "completed"


def test_live_pause_resume_and_cancel_fence_future_vertical_output(temporary_sqlite_db, tmp_path: Path) -> None:
    project = tmp_path / "cancel-project"
    project.mkdir()

    with TestClient(app) as client:
        created = client.post("/sessions/", json=_create_request(project))
        session_id = created.json()["id"]
        with client.websocket_connect(f"/ws/sessions/{session_id}?after_sequence=0") as socket:
            socket.receive_json()
            socket.send_json({"commandId": "start", "type": "session.start", "payload": {}})
            socket.receive_json()
            approval = _receive_type(socket, "approval.requested")
            socket.send_json({"commandId": "pause", "type": "session.pause", "payload": {}})
            assert _receive_status(socket, "paused")["payload"]["status"] == "paused"
            socket.send_json({"commandId": "resume", "type": "session.resume", "payload": {}})
            assert _receive_status(socket, "running")["payload"]["status"] == "running"
            socket.send_json({"commandId": "cancel", "type": "session.cancel", "payload": {"reasonSummary": "Stop before work starts."}})
            assert _receive_status(socket, "cancelled")["payload"]["status"] == "cancelled"

    assert approval["payload"]["approvalId"]
    assert not (Path(settings.db_path).parent / "workspaces" / session_id / "workspace" / "argus-vertical-task.txt").exists()


@pytest.mark.asyncio
async def test_preauthorized_vertical_task_continues_without_an_approval_prompt(
    temporary_sqlite_db, tmp_path: Path,
) -> None:
    project = tmp_path / "preauthorized-project"
    project.mkdir()

    async def run_preauthorized_task() -> list[object]:
        database = await get_db()
        try:
            session_id, runner = await _preauthorized_runner_session(
                database, project, tool_allowlist=["write_file"],
            )
            assert await runner.request_scoped_write_grant(session_id) is None
            await runner.run_after_grant(session_id)
            return await EventRepository(database).list_for_session(session_id)
        finally:
            await database.close()

    events = await run_preauthorized_task()

    statuses = [event.payload["status"] for event in events if event.event_type == "session.status_changed"]
    assert "completed" in statuses
    assert "waiting_approval" not in statuses


@pytest.mark.asyncio
async def test_application_shutdown_cancels_and_awaits_vertical_tasks() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def pending_step(_session_id: str, *, after_grant: bool) -> None:
        assert after_grant is True
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with patch.object(websocket_api, "_run_first_vertical_step", pending_step):
        websocket_api._schedule_first_vertical_step("session-shutdown", after_grant=True)
        await started.wait()
        await websocket_api.shutdown_vertical_tasks(grace_period_seconds=0)

    assert cancelled.is_set()
    assert not websocket_api._vertical_tasks


@pytest.mark.asyncio
async def test_profile_backed_coordinator_keeps_the_same_scheduler_and_permission_flow(
    temporary_sqlite_db, tmp_path: Path,
) -> None:
    class RecordedProvider:
        def __init__(self, builder_id: str) -> None:
            self._builder_id = builder_id
        async def stream(self, _: ProviderRequest):
            yield StructuredOutput({"type": "assignments", "routingSummary": "Profile-backed Coordinator assigned the Builder.", "assignments": [{"proposalId": "profile-backed", "assigneeAgentId": self._builder_id, "objective": "Create one reviewable file in the isolated workspace.", "acceptanceCriteria": ["Write the requested file", "Record a reviewable diff artifact"], "operationClass": "mutating", "requestedBudget": {}, "requestedCapabilities": ["workspace.write"], "requestedTools": ["write_file"], "reasonSummary": "The Builder has the approved workspace write capability."}]})
        async def cancel(self, _: str) -> None: return None

    seen: list[tuple[str, str]] = []
    builder_snapshot_id = ""
    async def resolve(profile_id: str, model_id: str) -> RecordedProvider:
        seen.append((profile_id, model_id))
        return RecordedProvider(builder_snapshot_id)

    database = await get_db()
    try:
        async def run(profile_id: str, model_id: str) -> list[object]:
            nonlocal builder_snapshot_id
            project = tmp_path / f"profile-backed-{model_id}"
            project.mkdir()
            session_id, runner = await _preauthorized_runner_session(
                database, project, tool_allowlist=["write_file"],
                model_binding={"providerProfileId": profile_id, "modelId": model_id}, provider_resolver=resolve, require_review=True,
            )
            configuration = await SessionConfigurationService(database).current(session_id)
            builder_snapshot_id = next(agent["id"] for agent in configuration.agent_snapshots if agent["role"] == "builder")
            assert await runner.request_scoped_write_grant(session_id) is None
            await runner.run_after_grant(session_id)
            return await EventRepository(database).list_for_session(session_id)

        first_events = await run("prv_alpha", "recorded-model-a")
        second_events = await run("prv_beta", "recorded-model-b")
    finally:
        await database.close()

    assert seen == [("prv_alpha", "recorded-model-a"), ("prv_beta", "recorded-model-b")]
    assert [event.event_type for event in first_events] == [event.event_type for event in second_events]
    assert [event.payload.get("status") for event in first_events if event.event_type == "gate.status_changed"] == [event.payload.get("status") for event in second_events if event.event_type == "gate.status_changed"]
    assert [event.payload.get("status") for event in first_events if event.event_type == "approval.resolved"] == [event.payload.get("status") for event in second_events if event.event_type == "approval.resolved"]
    assert any(event.event_type == "assignment.created" for event in first_events)
    assert any(event.event_type == "gate.status_changed" for event in first_events)


@pytest.mark.asyncio
async def test_vertical_task_fails_before_writing_when_execution_tool_fence_rejects_it(
    temporary_sqlite_db, tmp_path: Path,
) -> None:
    project = tmp_path / "tool-denied-project"
    project.mkdir()
    database = await get_db()
    try:
        session_id, runner = await _preauthorized_runner_session(
            database, project, tool_allowlist=["write_file"],
        )
        assert await runner.request_scoped_write_grant(session_id) is None
        snapshot = await SessionConfigurationService(database).current(session_id)
        builder_id = next(agent["id"] for agent in snapshot.agent_snapshots if agent["role"] == "builder")
        action = {
            "type": "assignments", "routingSummary": "Test the execution fence.",
            "assignments": [{
                "proposalId": f"proposal_{uuid.uuid4().hex}", "assigneeAgentId": builder_id,
                "objective": "Attempt one isolated write.", "acceptanceCriteria": ["Do not write without a tool grant"],
                "operationClass": "mutating", "requestedBudget": {},
                "requestedCapabilities": ["workspace.write"], "requestedTools": ["write_file"],
                "reasonSummary": "Exercise the immutable assignment snapshot fence.",
            }],
        }
        result = await CoordinatorCycle(database).execute(
            session_id, ScriptedProvider(((StructuredOutput(action),),)),
            ProviderRequest("tool-fence", "fake-provider", ({"role": "user", "content": "test"},)),
        )
        assert result.action is not None
        scheduled = await runner._running_builder_attempt(session_id)
        # The durable session-agent snapshot is immutable after scheduling.  A
        # different tool proves the real snapshot query rejects an unlisted
        # permission; mock the write fence to exercise the defensive worker
        # failure path that protects against a stale/corrupt executor input.
        with pytest.raises(PermissionError):
            await runner._require_assignment_tool_allowed(scheduled.assignment_id, "read_file")
        with pytest.raises(PermissionError, match="does not allow this tool"):
            with patch.object(
                runner, "_require_assignment_tool_allowed",
                AsyncMock(side_effect=PermissionError("The session agent definition does not allow this tool.")),
            ):
                await runner._write_and_complete(session_id, scheduled)
        events = await EventRepository(database).list_for_session(session_id)
        async with database.execute(
            "SELECT state, writer_lease_id FROM assignments WHERE session_id = ?", (session_id,),
        ) as cursor:
            assignment = await cursor.fetchone()
        assert assignment is not None
        async with database.execute(
            "SELECT released_at_ms FROM writer_leases WHERE id = ?", (assignment["writer_lease_id"],),
        ) as cursor:
            lease = await cursor.fetchone()
    finally:
        await database.close()

    assert assignment["state"] == "failed"
    assert lease is not None and lease["released_at_ms"] is not None
    assert not (Path(settings.db_path).parent / "workspaces" / session_id / "workspace" / "argus-vertical-task.txt").exists()
    assert not any(event.event_type == "artifact.diff_updated" for event in events)
    assert any(
        event.event_type == "assignment.failed" and event.payload["failureCode"] == "tool_not_allowed"
        for event in events
    )


def test_vertical_task_routes_required_review_before_it_can_complete(temporary_sqlite_db, tmp_path: Path) -> None:
    project = tmp_path / "gated-project"
    project.mkdir()

    with TestClient(app) as client:
        created = client.post("/sessions/", json=_create_request(project, require_review=True))
        session_id = created.json()["id"]
        with client.websocket_connect(f"/ws/sessions/{session_id}?after_sequence=0") as socket:
            socket.receive_json()
            socket.send_json({"commandId": "start", "type": "session.start", "payload": {}})
            socket.receive_json()
            approval = _receive_type(socket, "approval.requested")
            socket.send_json({
                "commandId": "grant", "type": "approval.resolve",
                "payload": {"approvalId": approval["payload"]["approvalId"], "resolution": "grant", "grantCapabilities": ["workspace.write"], "scopeSummary": "Isolated workspace only."},
            })
            _receive_type(socket, "approval.resolved")
            _receive_type(socket, "assignment.created")
            _receive_type(socket, "assignment.created")

    events = asyncio.run(_events(session_id))
    assert any(event.event_type == "gate.status_changed" and event.payload["status"] == "pending" for event in events)
    assert not any(event.event_type == "session.status_changed" and event.payload["status"] == "completed" for event in events)
