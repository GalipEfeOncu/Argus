from __future__ import annotations

import asyncio
import json
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.database import get_db, transaction
from app.db.repositories import EventRepository, SessionRepository, _now_ms
from app.providers.protocol import Finished, ProviderRequest, StructuredOutput, TextDelta, ToolCall, Usage
from app.providers.scripted import ScriptedProvider, SlowStream
from app.providers.adapters import ProviderDependencyUnavailable
from app.schemas.provider import ProviderProfileCreate
from app.schemas.project import WorkspaceMode
from app.schemas.session import RequiredRoleRule, SessionAgentInput, SessionConfigurationInput
from app.schemas.session_commands import parse_session_command
from app.services.command_processor import CommandProcessor
from app.services.provider_profile_service import ProviderProfileService
from app.services.session_configuration_service import SessionConfigurationService
from app.services.session_runtime_manager import SessionRuntimeManager
from app.services.session_runtime_manager import session_runtime_manager
from app.services.workspace_service import ProjectWorkspaceService, ScopedToolService
from app.main import app


async def _session(
    database, session_id: str = "runtime-session", *, required_builder_gate: bool = False,
    zero_limit: str | None = None,
) -> tuple[str, str]:
    profile = await ProviderProfileService(database).create(ProviderProfileCreate(
        providerKind="openai", displayName="Configured provider",
    ))
    await SessionRepository(database).create_legacy_session(
        session_id=session_id, name="Runtime", project_path="workspace",
        task="Use the stored goal exactly.", role_configs=[],
    )
    async with transaction(database):
        snapshot = await SessionConfigurationService(database).create_initial(
            session_id=session_id,
            agents=[
                SessionAgentInput.model_validate({
                    "id": "coordinator", "role": "coordinator",
                    "systemPrompt": "Return one bounded Coordinator action.",
                    "modelBinding": {"providerProfileId": profile.id, "modelId": "configured-model"},
                }),
                SessionAgentInput.model_validate({
                    "id": "builder", "role": "builder", "capabilities": ["workspace.read", "workspace.write"],
                    "toolAllowlist": ["read_file", "list_dir", "search_files"],
                    "modelBinding": {"providerProfileId": profile.id, "modelId": "configured-model"},
                }),
            ],
            coordinator_id="coordinator",
            configuration=SessionConfigurationInput.model_validate({
                "availableAgentIds": ["builder"],
                "requiredRoleRules": [RequiredRoleRule(
                    id="builder-gate", role="builder", applicability="always", successEvidence="verified_change",
                ).model_dump(by_alias=True)] if required_builder_gate else [],
                **({"executionLimits": {zero_limit: 0}} if zero_limit else {}),
            }),
            workspace_mode="snapshot", acknowledged_direct_write=False,
        )
    coordinator_id = next(agent["id"] for agent in snapshot.agent_snapshots if agent["role"] == "coordinator")
    return profile.id, coordinator_id


async def _start(database, session_id: str = "runtime-session", command_id: str = "start"):
    return await CommandProcessor(database).process(session_id, parse_session_command({
        "commandId": command_id, "type": "session.start", "payload": {},
    }))


async def _wait_for_status(database, status: str, session_id: str = "runtime-session") -> None:
    for _ in range(100):
        async with database.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)) as cursor:
            row = await cursor.fetchone()
        if row is not None and row["status"] == status:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"session did not reach {status}")


@pytest.mark.asyncio
async def test_start_is_single_flight_and_uses_stored_goal_and_immutable_binding(temporary_sqlite_db) -> None:
    database = await get_db()
    requests: list[ProviderRequest] = []
    resolutions: list[tuple[str, str]] = []

    async def resolver(profile_id: str, model_id: str):
        resolutions.append((profile_id, model_id))
        provider = ScriptedProvider(((SlowStream(0.02), StructuredOutput({
            "type": "final", "finalSummary": "The configured Coordinator finished.", "evidenceReferences": ["goal"],
        })),))
        original = provider.stream

        async def stream(request: ProviderRequest):
            requests.append(request)
            async for event in original(request):
                yield event

        provider.stream = stream  # type: ignore[method-assign]
        return provider

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        profile_id, _ = await _session(database)
        first = await _start(database)
        duplicate = await _start(database)
        assert not first.duplicate and duplicate.duplicate
        assert await manager.start("runtime-session") is True
        assert await manager.start("runtime-session") is False
        await _wait_for_status(database, "completed")
    finally:
        await manager.shutdown()
        await database.close()

    assert resolutions == [(profile_id, "configured-model")]
    assert requests[0].messages[-1] == {"role": "user", "content": "Use the stored goal exactly."}
    assert requests[0].response_schema is not None


@pytest.mark.asyncio
async def test_final_completes_with_visible_message_and_disconnected_replay(temporary_sqlite_db) -> None:
    database = await get_db()
    published: list[dict] = []

    async def resolver(_profile_id: str, _model_id: str):
        return ScriptedProvider(((StructuredOutput({
            "type": "final", "finalSummary": "Visible final result.", "evidenceReferences": ["goal"],
        }),),))

    async def publisher(_session_id: str, values: list[dict]) -> None:
        published.extend(values)

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=publisher)
    try:
        await _session(database)
        await _start(database)
        await manager.start("runtime-session")
        await _wait_for_status(database, "completed")
        events = await EventRepository(database).list_for_session("runtime-session")
    finally:
        await manager.shutdown()
        await database.close()

    assert [event.event_type for event in events] == [
        "session.status_changed", "session.status_changed", "message.created", "session.status_changed",
    ]
    assert events[-2].payload["content"] == "Visible final result."
    assert events[-2].payload["authorKind"] == "coordinator"
    assert [value["sequence"] for value in published] == [2, 3, 4]


@pytest.mark.asyncio
async def test_unmet_final_gate_fails_without_dispatching_specialist_work(temporary_sqlite_db) -> None:
    database = await get_db()
    final = {"type": "final", "finalSummary": "Unsupported completion.", "evidenceReferences": ["missing"]}

    async def resolver(_profile_id: str, _model_id: str):
        return ScriptedProvider(((StructuredOutput(final),), (StructuredOutput(final),)))

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(database, required_builder_gate=True)
        await _start(database)
        await manager.start("runtime-session")
        await _wait_for_status(database, "failed")
        async with database.execute("SELECT COUNT(*) AS total FROM assignments") as cursor:
            assignments = int((await cursor.fetchone())["total"])
        async with database.execute("SELECT COUNT(*) AS total FROM assignment_attempts") as cursor:
            attempts = int((await cursor.fetchone())["total"])
    finally:
        await manager.shutdown()
        await database.close()

    assert assignments == attempts == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("action,status", [
    ({"type": "ask_user", "routingSummary": "Need input.", "question": "Which approach should I use?"}, "paused"),
    ({"type": "wait", "routingSummary": "Waiting for an external prerequisite."}, "paused"),
    ({"type": "stop", "finalSummary": "Work stopped safely.", "reason": "The goal cannot be completed safely."}, "failed"),
])
async def test_non_assignment_actions_have_visible_honest_lifecycle(temporary_sqlite_db, action: dict, status: str) -> None:
    database = await get_db()

    async def resolver(_profile_id: str, _model_id: str):
        return ScriptedProvider(((StructuredOutput(action),),))

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(database)
        await _start(database)
        await manager.start("runtime-session")
        await _wait_for_status(database, status)
        events = await EventRepository(database).list_for_session("runtime-session")
    finally:
        await manager.shutdown()
        await database.close()

    assert any(event.event_type == "message.created" and event.actor_id == "coordinator" for event in events)


@pytest.mark.asyncio
async def test_user_message_and_resume_start_a_new_turn_after_ask_user(temporary_sqlite_db) -> None:
    database = await get_db()
    requests: list[ProviderRequest] = []
    actions = iter((
        {"type": "ask_user", "routingSummary": "Need input.", "question": "Which approach should I use?"},
        {"type": "final", "finalSummary": "Used the user's answer.", "evidenceReferences": ["answer"]},
    ))

    async def resolver(_profile_id: str, _model_id: str):
        provider = ScriptedProvider(((StructuredOutput(next(actions)),),))
        original = provider.stream

        async def stream(request: ProviderRequest):
            requests.append(request)
            async for event in original(request):
                yield event

        provider.stream = stream  # type: ignore[method-assign]
        return provider

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(database)
        await _start(database)
        await manager.start("runtime-session")
        await _wait_for_status(database, "paused")
        await CommandProcessor(database).process("runtime-session", parse_session_command({
            "commandId": "answer", "type": "message.send", "payload": {"content": "Use the safer approach."},
        }))
        await CommandProcessor(database).process("runtime-session", parse_session_command({
            "commandId": "resume", "type": "session.resume", "payload": {},
        }))
        assert await manager.start("runtime-session") is True
        await _wait_for_status(database, "completed")
    finally:
        await manager.shutdown()
        await database.close()

    assert requests[-1].messages[-1] == {"role": "user", "content": "Use the safer approach."}


@pytest.mark.asyncio
async def test_provider_resolution_failure_is_redacted_and_terminal(temporary_sqlite_db) -> None:
    database = await get_db()

    async def unavailable(_profile_id: str, _model_id: str):
        raise ProviderDependencyUnavailable("secret raw dependency detail")

    manager = SessionRuntimeManager(provider_resolver=unavailable, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(database)
        await _start(database)
        await manager.start("runtime-session")
        await _wait_for_status(database, "failed")
        events = await EventRepository(database).list_for_session("runtime-session")
    finally:
        await manager.shutdown()
        await database.close()

    error = next(event for event in events if event.event_type == "error.created")
    assert error.payload["code"] == "coordinator_provider_unavailable"
    assert "secret" not in json.dumps(error.payload)


@pytest.mark.asyncio
async def test_direct_chat_streams_plain_text_into_the_ordered_timeline(temporary_sqlite_db) -> None:
    database = await get_db()
    requests: list[ProviderRequest] = []
    published: list[dict] = []

    async def resolver(_profile_id: str, _model_id: str):
        provider = ScriptedProvider(((TextDelta("Hello"), TextDelta(" from chat"), Usage(input_tokens=2, output_tokens=3), Finished()),))
        original = provider.stream

        async def stream(request: ProviderRequest):
            requests.append(request)
            async for event in original(request):
                yield event

        provider.stream = stream  # type: ignore[method-assign]
        return provider

    async def publisher(_session_id: str, values: list[dict]) -> None:
        published.extend(values)

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=publisher)
    try:
        profile_id, _ = await _session(database)
        await database.execute(
            "UPDATE sessions SET session_type = 'chat', project_path = '', status = 'running' WHERE id = ?",
            ("runtime-session",),
        )
        await database.commit()
        await CommandProcessor(database).process("runtime-session", parse_session_command({
            "commandId": "chat-message", "type": "message.send", "payload": {"content": "Say hello."},
        }))
        assert await manager.start("runtime-session") is True
        await manager.wait("runtime-session")
        events = await EventRepository(database).list_for_session("runtime-session")
        async with database.execute(
            "SELECT operation_kind, state FROM provider_operations WHERE session_id = ?", ("runtime-session",)
        ) as cursor:
            operation = await cursor.fetchone()
    finally:
        await manager.shutdown()
        await database.close()

    assert requests[0].messages[-1] == {"role": "user", "content": "Say hello."}
    assert [event.event_type for event in events if event.event_type.startswith("message.")] == [
        "message.created", "message.created", "message.delta", "message.completed",
    ]
    assert events[-1].event_type == "message.completed"
    assert any(event.event_type == "usage.updated" for event in events)
    assert [value["type"] for value in published] == [
        "message.created", "message.delta", "usage.updated", "message.completed",
    ]
    assert operation is not None and operation["operation_kind"] == "chat" and operation["state"] == "succeeded"
    assert profile_id


@pytest.mark.asyncio
async def test_deleted_provider_profile_fails_closed_without_a_fallback(temporary_sqlite_db) -> None:
    database = await get_db()
    manager = SessionRuntimeManager(publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        profile_id, _ = await _session(database)
        await ProviderProfileService(database).delete(profile_id)
        await _start(database)
        await manager.start("runtime-session")
        await _wait_for_status(database, "failed")
        events = await EventRepository(database).list_for_session("runtime-session")
    finally:
        await manager.shutdown()
        await database.close()

    assert next(event.payload["code"] for event in events if event.event_type == "error.created") == "coordinator_provider_unavailable"


@pytest.mark.asyncio
async def test_provider_failure_after_resume_does_not_leave_the_session_running(temporary_sqlite_db) -> None:
    database = await get_db()
    manager = SessionRuntimeManager(publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        profile_id, _ = await _session(database)
        await _start(database)
        await EventRepository(database).append(
            event_id="ready", session_id="runtime-session", event_type="session.status_changed", actor_id="system",
            payload={"status": "running"}, timestamp_ms=1,
        )
        await CommandProcessor(database).process("runtime-session", parse_session_command({
            "commandId": "pause", "type": "session.pause", "payload": {},
        }))
        await ProviderProfileService(database).delete(profile_id)
        await CommandProcessor(database).process("runtime-session", parse_session_command({
            "commandId": "resume", "type": "session.resume", "payload": {},
        }))
        await manager.start("runtime-session")
        await _wait_for_status(database, "failed")
    finally:
        await manager.shutdown()
        await database.close()


@pytest.mark.asyncio
async def test_missing_immutable_coordinator_configuration_fails_visibly(temporary_sqlite_db) -> None:
    database = await get_db()
    manager = SessionRuntimeManager(publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await SessionRepository(database).create_legacy_session(
            session_id="runtime-session", name="Missing configuration", project_path="workspace",
            task="Fail safely.", role_configs=[],
        )
        await _start(database)
        await manager.start("runtime-session")
        await _wait_for_status(database, "failed")
        events = await EventRepository(database).list_for_session("runtime-session")
    finally:
        await manager.shutdown()
        await database.close()

    assert next(event.payload["code"] for event in events if event.event_type == "error.created") == "coordinator_configuration_missing"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_class", ["read_only", "mutating"])
async def test_assignment_without_specialist_executor_fails_honestly_without_a_running_attempt(
    temporary_sqlite_db, operation_class: str,
) -> None:
    database = await get_db()
    builder_id = ""

    async def resolver(_profile_id: str, _model_id: str):
        return ScriptedProvider(((StructuredOutput({
            "type": "assignments", "routingSummary": "Delegate bounded work.",
            "assignments": [{
                "proposalId": f"proposal-{operation_class}", "assigneeAgentId": builder_id,
                "objective": "Inspect the workspace.", "acceptanceCriteria": ["Report a result."],
                "operationClass": operation_class, "requestedBudget": {},
                "requestedCapabilities": ["workspace.write" if operation_class == "mutating" else "workspace.read"],
                "requestedTools": [], "reasonSummary": "The Builder is eligible.",
            }],
        }),),))

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(database)
        snapshot = await SessionConfigurationService(database).current("runtime-session")
        builder_id = snapshot.available_agent_ids[0]
        await _start(database)
        await manager.start("runtime-session")
        for _ in range(100):
            async with database.execute("SELECT state FROM assignments LIMIT 1") as cursor:
                assignment = await cursor.fetchone()
            async with database.execute("SELECT status FROM sessions WHERE id = 'runtime-session'") as cursor:
                current_status = (await cursor.fetchone())["status"]
            if current_status == "failed":
                break
            await asyncio.sleep(0.005)
        async with database.execute("SELECT COUNT(*) AS total FROM assignment_attempts") as cursor:
            attempts = int((await cursor.fetchone())["total"])
        async with database.execute("SELECT status FROM sessions WHERE id = 'runtime-session'") as cursor:
            status = (await cursor.fetchone())["status"]
        events = await EventRepository(database).list_for_session("runtime-session")
    finally:
        await manager.shutdown()
        await database.close()

    if operation_class == "read_only":
        assert assignment is not None and assignment["state"] == "failed"
        assert attempts == 1
    else:
        assert assignment is None
        assert attempts == 0
    assert status == "failed"
    assert any(event.event_type == "error.created" and event.payload["recoverable"] for event in events)


@pytest.mark.asyncio
async def test_multi_proposal_turn_fails_before_any_assignment_is_created(temporary_sqlite_db) -> None:
    database = await get_db()
    builder_id = ""

    async def resolver(_profile_id: str, _model_id: str):
        base = {
            "assigneeAgentId": builder_id, "objective": "Inspect safely.",
            "acceptanceCriteria": ["Report a result."], "requestedBudget": {}, "requestedTools": [],
            "reasonSummary": "The Builder is eligible.",
        }
        return ScriptedProvider(((StructuredOutput({
            "type": "assignments", "routingSummary": "Try bounded work.", "assignments": [
                {**base, "proposalId": "read-first", "operationClass": "read_only", "requestedCapabilities": ["workspace.read"]},
                {**base, "proposalId": "write-second", "operationClass": "mutating", "requestedCapabilities": ["workspace.write"]},
            ],
        }),),))

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(database)
        builder_id = (await SessionConfigurationService(database).current("runtime-session")).available_agent_ids[0]
        await _start(database)
        await manager.start("runtime-session")
        await _wait_for_status(database, "failed")
        async with database.execute("SELECT state FROM assignments") as cursor:
            states = [str(row["state"]) for row in await cursor.fetchall()]
        async with database.execute("SELECT COUNT(*) AS total FROM assignment_attempts") as cursor:
            attempts = int((await cursor.fetchone())["total"])
    finally:
        await manager.shutdown()
        await database.close()

    assert states == []
    assert attempts == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("command,target", [("session.pause", "paused"), ("session.cancel", "cancelled")])
async def test_pause_and_cancel_fence_late_coordinator_output(temporary_sqlite_db, command: str, target: str) -> None:
    database = await get_db()

    async def resolver(_profile_id: str, _model_id: str):
        return ScriptedProvider(((SlowStream(0.05), StructuredOutput({
            "type": "final", "finalSummary": "Late output.", "evidenceReferences": ["late"],
        })),))

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    control_db = await get_db()
    try:
        await _session(database)
        await _start(database)
        await manager.start("runtime-session")
        await _wait_for_status(database, "running")
        await CommandProcessor(control_db).process("runtime-session", parse_session_command({
            "commandId": "control", "type": command, "payload": {},
        }))
        await asyncio.sleep(0.08)
        events = await EventRepository(database).list_for_session("runtime-session")
    finally:
        await manager.shutdown()
        await control_db.close()
        await database.close()

    assert not any(event.event_type == "message.created" and event.payload.get("content") == "Late output." for event in events)
    assert next(event.payload["status"] for event in reversed(events) if event.event_type == "session.status_changed") == target


@pytest.mark.asyncio
async def test_restart_recovery_does_not_replay_unknown_coordinator_operation(temporary_sqlite_db) -> None:
    database = await get_db()
    calls = 0

    async def resolver(_profile_id: str, _model_id: str):
        nonlocal calls
        calls += 1
        return ScriptedProvider()

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(database)
        await EventRepository(database).append(
            event_id="running", session_id="runtime-session", event_type="session.status_changed", actor_id="system",
            payload={"status": "running"}, timestamp_ms=1,
        )
        await database.execute(
            """INSERT INTO provider_operations (id, session_id, operation_kind, mutation_class, state,
               request_fingerprint, started_at_ms) VALUES ('lost', 'runtime-session', 'coordinator', 'read_only',
               'outcome_unknown', 'fingerprint', 1)"""
        )
        await database.commit()
        assert await manager.recover_after_restart() == 1
        await _wait_for_status(database, "failed")
    finally:
        await manager.shutdown()
        await database.close()

    assert calls == 0


@pytest.mark.asyncio
async def test_shutdown_cancels_an_inflight_coordinator_within_the_bound(temporary_sqlite_db) -> None:
    database = await get_db()
    provider = ScriptedProvider(((SlowStream(10),),))

    async def resolver(_profile_id: str, _model_id: str):
        return provider

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(database)
        await _start(database)
        await manager.start("runtime-session")
        await _wait_for_status(database, "running")
        await asyncio.wait_for(manager.shutdown(timeout_seconds=0.01), timeout=0.2)
    finally:
        await database.close()

    assert manager._tasks == {}


def test_websocket_fans_out_start_before_runtime_events_and_duplicate_does_not_rerun_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "websocket-runtime.db"))
    project = tmp_path / "project"
    project.mkdir()
    requests: list[ProviderRequest] = []

    async def resolver(_profile_id: str, _model_id: str):
        provider = ScriptedProvider(((StructuredOutput({
            "type": "final", "finalSummary": "Canonical final.", "evidenceReferences": ["goal"],
        }),),))
        original = provider.stream

        async def stream(request: ProviderRequest):
            requests.append(request)
            async for event in original(request):
                yield event

        provider.stream = stream  # type: ignore[method-assign]
        return provider

    previous_resolver = session_runtime_manager._provider_resolver
    session_runtime_manager._provider_resolver = resolver
    try:
        with TestClient(app) as client:
            profile = client.post("/providers/", json={"providerKind": "openai", "displayName": "Configured provider"}).json()
            created = client.post("/sessions/", json={
                "projectPath": str(project), "goal": "Run the configured Coordinator.",
                "coordinatorAgentId": "coordinator",
                "agents": [{
                    "id": "coordinator", "role": "coordinator",
                    "modelBinding": {"providerProfileId": profile["id"], "modelId": "configured-model"},
                }],
                "configuration": {"availableAgentIds": []},
            })
            assert created.status_code == 200
            with client.websocket_connect(f"/ws/sessions/{created.json()['id']}?after_sequence=0") as socket:
                assert socket.receive_json()["type"] == "session.snapshot"
                start = {"commandId": "start-once", "type": "session.start", "payload": {}}
                socket.send_json(start)
                values = [socket.receive_json() for _ in range(4)]
                assert [value["type"] for value in values] == [
                    "session.status_changed", "session.status_changed", "message.created", "session.status_changed",
                ]
                assert [value["payload"].get("status") for value in values if value["type"] == "session.status_changed"] == [
                    "preparing", "running", "completed",
                ]
                socket.send_json(start)
                duplicate = socket.receive_json()
                assert duplicate["eventId"] == values[0]["eventId"]
    finally:
        session_runtime_manager._provider_resolver = previous_resolver

    assert len(requests) == 1


@pytest.mark.asyncio
async def test_read_only_specialist_tool_result_returns_to_coordinator_and_completes(
    temporary_sqlite_db, tmp_path: Path,
) -> None:
    database = await get_db()
    await _session(database)
    builder_id = (await SessionConfigurationService(database).current("runtime-session")).available_agent_ids[0]
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("Argus specialist evidence\n", encoding="utf-8")
    workspaces = ProjectWorkspaceService(database, managed_root=Path(settings.db_path).resolve().parent / "workspaces")
    project = await workspaces.register_project(str(source))
    await workspaces.prepare_workspace(session_id="runtime-session", project_id=str(project["id"]), mode=WorkspaceMode.snapshot)
    coordinator = ScriptedProvider(((StructuredOutput({
        "type": "assignments", "routingSummary": "Inspect the bounded workspace.",
        "assignments": [{
            "proposalId": "read-proposal", "assigneeAgentId": builder_id,
            "objective": "Read the project overview.", "acceptanceCriteria": ["Report README evidence."],
            "operationClass": "read_only", "requestedBudget": {},
            "requestedCapabilities": ["workspace.read"], "requestedTools": ["read_file"],
            "reasonSummary": "The configured specialist can inspect the file.",
        }],
    }),),))
    specialist = ScriptedProvider((
        (ToolCall("read-call-1", "read_file", {"path": "README.md"}),),
        (StructuredOutput({"summary": "README confirms Argus specialist evidence.", "evidence": []}),),
    ))
    follow_up = ScriptedProvider(((StructuredOutput({
        "type": "final", "finalSummary": "The configured specialist verified the README.",
        "evidenceReferences": ["read-proposal"],
    }),),))
    providers = iter((coordinator, specialist, follow_up))

    async def resolver(_profile_id: str, _model_id: str):
        return next(providers)

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _start(database)
        await manager.start("runtime-session")
        await _wait_for_status(database, "completed")
        events = await EventRepository(database).list_for_session("runtime-session")
        async with database.execute("SELECT exit_state, request_summary, result_summary FROM tool_executions") as cursor:
            tool = await cursor.fetchone()
    finally:
        await manager.shutdown()
        await database.close()

    assert [event.event_type for event in events if event.event_type.startswith("tool.")] == [
        "tool.requested", "tool.started", "tool.completed",
    ]
    assert tool["exit_state"] == "succeeded"
    assert "README.md" not in tool["request_summary"] and "Argus specialist evidence" not in tool["result_summary"]
    transcript = specialist.requests[1].messages
    assert transcript[-2]["role"] == "assistant" and transcript[-2]["tool_calls"][0]["id"] == "read-call-1"
    assert transcript[-1] == {"role": "tool", "content": "Argus specialist evidence\n", "tool_call_id": "read-call-1", "name": "read_file"}
    assert events[-2].payload["content"] == "The configured specialist verified the README."
    assert (source / "README.md").read_text(encoding="utf-8") == "Argus specialist evidence\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(("command", "target"), [("session.pause", "paused"), ("session.cancel", "cancelled")])
async def test_pause_and_cancel_fence_late_specialist_output(
    temporary_sqlite_db, command: str, target: str,
) -> None:
    database = await get_db()
    await _session(database)
    builder_id = (await SessionConfigurationService(database).current("runtime-session")).available_agent_ids[0]
    coordinator = ScriptedProvider(((StructuredOutput({
        "type": "assignments", "routingSummary": "Inspect safely.",
        "assignments": [{
            "proposalId": "slow-read", "assigneeAgentId": builder_id, "objective": "Inspect.",
            "acceptanceCriteria": ["Report."], "operationClass": "read_only", "requestedBudget": {},
            "requestedCapabilities": ["workspace.read"], "requestedTools": [], "reasonSummary": "Eligible.",
        }],
    }),),))
    specialist = ScriptedProvider(((SlowStream(0.08), StructuredOutput({"summary": "Late specialist output.", "evidence": []})),))
    providers = iter((coordinator, specialist))

    async def resolver(_profile_id: str, _model_id: str):
        return next(providers)

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _start(database)
        await manager.start("runtime-session")
        for _ in range(100):
            async with database.execute("SELECT state FROM assignments LIMIT 1") as cursor:
                row = await cursor.fetchone()
            if row is not None and row["state"] == "running":
                break
            await asyncio.sleep(0.005)
        await CommandProcessor(database).process("runtime-session", parse_session_command({
            "commandId": f"specialist-{target}", "type": command, "payload": {},
        }))
        await manager.wait("runtime-session")
        events = await EventRepository(database).list_for_session("runtime-session")
        async with database.execute("SELECT status FROM sessions WHERE id = 'runtime-session'") as cursor:
            status = (await cursor.fetchone())["status"]
    finally:
        await manager.shutdown()
        await database.close()

    assert status == target
    assert not any(event.event_type == "assignment.completed" for event in events)
    assert not any(event.event_type == "message.created" and event.payload.get("content") == "Late specialist output." for event in events)


@pytest.mark.asyncio
async def test_pause_during_read_tool_records_cancelled_tool_and_fences_result(
    temporary_sqlite_db, tmp_path: Path, monkeypatch,
) -> None:
    database = await get_db()
    await _session(database)
    builder_id = (await SessionConfigurationService(database).current("runtime-session")).available_agent_ids[0]
    source = tmp_path / "slow-source"
    source.mkdir()
    (source / "README.md").write_text("late secret content\n", encoding="utf-8")
    workspaces = ProjectWorkspaceService(database, managed_root=Path(settings.db_path).resolve().parent / "workspaces")
    project = await workspaces.register_project(str(source))
    await workspaces.prepare_workspace(session_id="runtime-session", project_id=str(project["id"]), mode=WorkspaceMode.snapshot)
    original_read = ScopedToolService.read_text

    def slow_read(self, path: str, *, max_characters=None):
        time.sleep(0.08)
        return original_read(self, path, max_characters=max_characters)

    monkeypatch.setattr(ScopedToolService, "read_text", slow_read)
    coordinator = ScriptedProvider(((StructuredOutput({
        "type": "assignments", "routingSummary": "Inspect safely.",
        "assignments": [{
            "proposalId": "slow-tool", "assigneeAgentId": builder_id, "objective": "Read.",
            "acceptanceCriteria": ["Report."], "operationClass": "read_only", "requestedBudget": {},
            "requestedCapabilities": ["workspace.read"], "requestedTools": ["read_file"], "reasonSummary": "Eligible.",
        }],
    }),),))
    specialist = ScriptedProvider(((ToolCall("slow-call", "read_file", {"path": "README.md"}),),))
    providers = iter((coordinator, specialist))

    async def resolver(_profile_id: str, _model_id: str):
        return next(providers)

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _start(database)
        await manager.start("runtime-session")
        for _ in range(100):
            events = await EventRepository(database).list_for_session("runtime-session")
            if any(event.event_type == "tool.started" for event in events):
                break
            await asyncio.sleep(0.005)
        await CommandProcessor(database).process("runtime-session", parse_session_command({
            "commandId": "pause-tool", "type": "session.pause", "payload": {},
        }))
        await manager.wait("runtime-session")
        events = await EventRepository(database).list_for_session("runtime-session")
        async with database.execute("SELECT exit_state, result_summary FROM tool_executions") as cursor:
            tool = await cursor.fetchone()
    finally:
        await manager.shutdown()
        await database.close()

    assert tool["exit_state"] == "cancelled"
    assert "late secret content" not in json.dumps([event.payload for event in events])
    assert not any(event.event_type == "assignment.completed" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize(("limit_name", "expected_resolutions"), [
    ("maxModelIterationsPerAssignment", 1), ("maxToolCallsPerAssignment", 2),
])
async def test_zero_specialist_limits_prevent_provider_turn_or_tool_start(
    temporary_sqlite_db, limit_name: str, expected_resolutions: int,
) -> None:
    database = await get_db()
    await _session(database, zero_limit=limit_name)
    builder_id = (await SessionConfigurationService(database).current("runtime-session")).available_agent_ids[0]
    coordinator = ScriptedProvider(((StructuredOutput({
        "type": "assignments", "routingSummary": "Inspect safely.",
        "assignments": [{
            "proposalId": f"zero-{limit_name}", "assigneeAgentId": builder_id, "objective": "Read.",
            "acceptanceCriteria": ["Report."], "operationClass": "read_only", "requestedBudget": {},
            "requestedCapabilities": ["workspace.read"], "requestedTools": ["read_file"], "reasonSummary": "Eligible.",
        }],
    }),),))
    specialist = ScriptedProvider(((ToolCall("must-not-start", "read_file", {"path": "README.md"}),),))
    providers = iter((coordinator, specialist))
    resolutions = 0

    async def resolver(_profile_id: str, _model_id: str):
        nonlocal resolutions
        resolutions += 1
        return next(providers)

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _start(database)
        await manager.start("runtime-session")
        await _wait_for_status(database, "failed")
        async with database.execute("SELECT COUNT(*) AS total FROM tool_executions") as cursor:
            tool_count = int((await cursor.fetchone())["total"])
    finally:
        await manager.shutdown()
        await database.close()

    assert resolutions == expected_resolutions
    assert tool_count == 0
