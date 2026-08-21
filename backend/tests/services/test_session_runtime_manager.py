from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.database import get_db, transaction
from app.db.repositories import EventRepository, SessionRepository, _now_ms
from app.providers.protocol import ProviderRequest, StructuredOutput
from app.providers.scripted import ScriptedProvider, SlowStream
from app.providers.adapters import ProviderDependencyUnavailable
from app.schemas.provider import ProviderProfileCreate
from app.schemas.session import RequiredRoleRule, SessionAgentInput, SessionConfigurationInput
from app.schemas.session_commands import parse_session_command
from app.services.command_processor import CommandProcessor
from app.services.provider_profile_service import ProviderProfileService
from app.services.session_configuration_service import SessionConfigurationService
from app.services.session_runtime_manager import SessionRuntimeManager
from app.services.session_runtime_manager import session_runtime_manager
from app.main import app


async def _session(
    database, session_id: str = "runtime-session", *, required_builder_gate: bool = False,
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
                    "modelBinding": {"providerProfileId": profile.id, "modelId": "configured-model"},
                }),
            ],
            coordinator_id="coordinator",
            configuration=SessionConfigurationInput(
                availableAgentIds=["builder"],
                requiredRoleRules=[RequiredRoleRule(
                    id="builder-gate", role="builder", applicability="always", successEvidence="verified_change",
                )] if required_builder_gate else [],
            ),
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
            if assignment is not None and assignment["state"] == "failed":
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
    else:
        assert assignment is None
    assert attempts == 0 and status == "failed"
    assert any(event.event_type == "error.created" and event.payload["recoverable"] for event in events)


@pytest.mark.asyncio
async def test_later_rejected_proposal_does_not_leave_an_earlier_assignment_created(temporary_sqlite_db) -> None:
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

    assert states == ["failed"]
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
