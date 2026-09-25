"""Durable human-turn and recovered-assignment delivery in the process runtime."""

from __future__ import annotations

import asyncio

import pytest

from app.db.database import get_db
from app.db.repositories import EventRepository, _now_ms
from app.providers.protocol import Finished, ProviderRequest, StructuredOutput, TextDelta
from app.providers.scripted import ScriptedProvider, SlowStream
from app.schemas.coordinator_actions import CoordinatorAssignment
from app.schemas.session_commands import parse_session_command
from app.services.assignment_scheduler import AssignmentScheduler
from app.services.command_processor import CommandProcessor, CommandRejected
from app.services.participant_instruction_service import ParticipantInstructionService
from app.services.recovery_service import RecoveryService
from app.services.session_configuration_service import SessionConfigurationService
from app.services.session_runtime_manager import SessionRuntimeManager
from tests.services.test_session_runtime_manager import _session, _start


async def _running(database) -> None:
    await _start(database)
    await EventRepository(database).append(
        event_id="ready-running", session_id="runtime-session", event_type="session.status_changed",
        actor_id="system", payload={"status": "running", "reasonSummary": "Ready."}, timestamp_ms=_now_ms(),
    )


async def _send(database, command_id: str, content: str, mention_ids: list[str] | None = None):
    return await CommandProcessor(database).process("runtime-session", parse_session_command({
        "commandId": command_id, "type": "message.send",
        "payload": {"content": content, "mentionIds": mention_ids or []},
    }))


@pytest.mark.asyncio
async def test_project_followup_supersedes_stream_and_starts_exactly_one_new_turn(temporary_sqlite_db) -> None:
    db = await get_db()
    entered = asyncio.Event()
    requests: list[ProviderRequest] = []
    first = ScriptedProvider(((SlowStream(0.05), StructuredOutput({
        "type": "final", "finalSummary": "Stale result", "evidenceReferences": ["goal"],
    })),))
    second = ScriptedProvider(((StructuredOutput({
        "type": "final", "finalSummary": "Fresh response", "evidenceReferences": ["new message"],
    }),),))
    providers = iter((first, second))

    async def resolver(_profile_id: str, _model_id: str):
        provider = next(providers)
        original = provider.stream

        async def stream(request: ProviderRequest):
            requests.append(request)
            entered.set()
            async for event in original(request):
                yield event

        provider.stream = stream  # type: ignore[method-assign]
        return provider

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(db)
        await _start(db)
        assert await manager.start("runtime-session")
        await asyncio.wait_for(entered.wait(), 1)
        sent = await _send(db, "followup", "Use the new instruction.")
        assert not sent.duplicate
        assert not await manager.start("runtime-session")
        await manager.wait("runtime-session")
        events = await EventRepository(db).list_for_session("runtime-session")
        async with db.execute("SELECT status FROM sessions WHERE id = 'runtime-session'") as cursor:
            status = (await cursor.fetchone())["status"]
    finally:
        await manager.shutdown()
        await db.close()

    assert status == "completed"
    assert len(requests) == 2
    assert requests[1].messages[-1] == {"role": "user", "content": "Use the new instruction."}
    assert not any(event.payload.get("content") == "Stale result" for event in events)
    assert sum(event.payload.get("content") == "Fresh response" for event in events) == 1


@pytest.mark.asyncio
async def test_pending_message_fences_stale_project_final_atomically(temporary_sqlite_db) -> None:
    db = await get_db()
    manager = SessionRuntimeManager(publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        _, coordinator_id = await _session(db)
        await _running(db)
        await _send(db, "latest-before-final", "Handle this before completing")
        await manager._message_and_status(
            db, "runtime-session", coordinator_id, "Stale final", "completed", "Old turn finished.",
        )
        async with db.execute("SELECT status FROM sessions WHERE id = 'runtime-session'") as cursor:
            status = (await cursor.fetchone())["status"]
        events = await EventRepository(db).list_for_session("runtime-session")
    finally:
        await manager.shutdown()
        await db.close()

    assert status == "running"
    assert not any(event.payload.get("content") == "Stale final" for event in events)


@pytest.mark.asyncio
async def test_chat_message_during_stream_gets_ordered_second_response(temporary_sqlite_db) -> None:
    db = await get_db()
    entered = asyncio.Event()
    requests: list[ProviderRequest] = []
    first = ScriptedProvider(((TextDelta("First"), SlowStream(0.05), TextDelta(" answer"), Finished()),))
    second = ScriptedProvider(((TextDelta("Second answer"), Finished()),))
    providers = iter((first, second))

    async def resolver(_profile_id: str, _model_id: str):
        provider = next(providers)
        original = provider.stream

        async def stream(request: ProviderRequest):
            requests.append(request)
            entered.set()
            async for event in original(request):
                yield event

        provider.stream = stream  # type: ignore[method-assign]
        return provider

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(db)
        await db.execute("UPDATE sessions SET session_type = 'chat', status = 'running' WHERE id = 'runtime-session'")
        await db.commit()
        await _send(db, "chat-one", "First question")
        await manager.start("runtime-session")
        await asyncio.wait_for(entered.wait(), 1)
        await _send(db, "chat-two", "Second question")
        assert not await manager.start("runtime-session")
        await manager.wait("runtime-session")
        events = await EventRepository(db).list_for_session("runtime-session")
    finally:
        await manager.shutdown()
        await db.close()

    assert len(requests) == 2
    assert requests[0].messages[-1] == {"role": "user", "content": "First question"}
    assert requests[1].messages[-1] == {"role": "user", "content": "Second question"}
    assert {"role": "assistant", "content": "First answer", "tool_calls": []} in requests[1].messages
    assert [event.event_type for event in events].count("message.completed") == 2


@pytest.mark.asyncio
async def test_explicit_mention_dispatches_target_once_and_duplicate_command_replays_receipt(temporary_sqlite_db) -> None:
    db = await get_db()
    specialist = ScriptedProvider(((StructuredOutput({"summary": "Target specialist responded.", "evidence": []}),),))
    coordinator = ScriptedProvider(((StructuredOutput({
        "type": "final", "finalSummary": "Target response reviewed.", "evidenceReferences": ["mention"],
    }),),))
    providers = iter((specialist, coordinator))

    async def resolver(_profile_id: str, _model_id: str):
        return next(providers)

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(db)
        await _running(db)
        builder = (await SessionConfigurationService(db).current("runtime-session")).available_agent_ids[0]
        first = await _send(db, "mention-once", "@builder inspect the goal", [builder])
        duplicate = await _send(db, "mention-once", "@builder inspect the goal", [builder])
        await manager.start("runtime-session")
        await manager.wait("runtime-session")
        async with db.execute("SELECT actor_id, validation_state FROM assignment_proposals") as cursor:
            proposals = await cursor.fetchall()
        async with db.execute("SELECT state FROM participant_instructions") as cursor:
            instructions = await cursor.fetchall()
        events = await EventRepository(db).list_for_session("runtime-session")
    finally:
        await manager.shutdown()
        await db.close()

    assert duplicate.duplicate and duplicate.events[0].event_id == first.events[0].event_id
    assert [(row["actor_id"], row["validation_state"]) for row in proposals] == [("human", "accepted")]
    assert [row["state"] for row in instructions] == ["delivered"]
    assert len(specialist.requests) == 1
    assert any(event.event_type == "assignment.completed" for event in events)


@pytest.mark.asyncio
async def test_restart_dispatches_orphaned_read_only_assignment_without_replaying_unsafe_work(temporary_sqlite_db) -> None:
    db = await get_db()
    specialist = ScriptedProvider(((StructuredOutput({"summary": "Recovered read-only result.", "evidence": []}),),))
    coordinator = ScriptedProvider(((StructuredOutput({
        "type": "final", "finalSummary": "Recovered result reviewed.", "evidenceReferences": ["recovered"],
    }),),))
    providers = iter((specialist, coordinator))

    async def resolver(_profile_id: str, _model_id: str):
        return next(providers)

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(db)
        await _running(db)
        builder = (await SessionConfigurationService(db).current("runtime-session")).available_agent_ids[0]
        assignment_id = await AssignmentScheduler(db).accept_coordinator_proposal("runtime-session", CoordinatorAssignment.model_validate({
            "proposalId": "recover-proposal", "assigneeAgentId": builder,
            "objective": "Inspect safely.", "acceptanceCriteria": ["Report result."],
            "operationClass": "read_only", "requestedBudget": {},
            "requestedCapabilities": ["workspace.read"], "requestedTools": [], "reasonSummary": "Read-only recovery test.",
        }), require_running=True)
        first_attempt = (await AssignmentScheduler(db).dispatch_ready("runtime-session", assignment_ids=(assignment_id,)))[0]
        report = await RecoveryService(db).recover_after_restart()
        assert report.orphaned_attempts == 1
        assert await manager.resume_queued_after_restart() == 1
        await manager.wait("runtime-session")
        async with db.execute("SELECT attempt_number, state FROM assignment_attempts ORDER BY attempt_number") as cursor:
            attempts = await cursor.fetchall()
        events = await EventRepository(db).list_for_session("runtime-session")
    finally:
        await manager.shutdown()
        await db.close()

    assert first_attempt.attempt_id
    assert [(row["attempt_number"], row["state"]) for row in attempts] == [(1, "orphaned"), (2, "completed")]
    assert len(specialist.requests) == 1
    assert any(event.event_type == "assignment.completed" for event in events)


@pytest.mark.asyncio
async def test_restart_wakes_preparing_session_before_any_provider_operation(temporary_sqlite_db) -> None:
    db = await get_db()
    provider = ScriptedProvider(((StructuredOutput({
        "type": "final", "finalSummary": "Initial turn resumed safely.", "evidenceReferences": ["goal"],
    }),),))

    async def resolver(_profile_id: str, _model_id: str):
        return provider

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(db)
        await _start(db)
        await RecoveryService(db).recover_after_restart()
        assert await manager.recover_after_restart() == 0
        assert await manager.resume_queued_after_restart() == 1
        await manager.wait("runtime-session")
        async with db.execute("SELECT status FROM sessions WHERE id = 'runtime-session'") as cursor:
            status = (await cursor.fetchone())["status"]
    finally:
        await manager.shutdown()
        await db.close()

    assert status == "completed"
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_restart_reports_interrupted_instruction_and_keeps_never_started_message_pending(temporary_sqlite_db) -> None:
    db = await get_db()
    provider = ScriptedProvider(((StructuredOutput({
        "type": "final", "finalSummary": "The pending second instruction was handled.",
        "evidenceReferences": ["second"],
    }),),))

    async def resolver(_profile_id: str, _model_id: str):
        return provider

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(db)
        await _running(db)
        await _send(db, "started-instruction", "First instruction")
        await _send(db, "never-started", "Second instruction")
        service = ParticipantInstructionService(db)
        first = await service.next_pending("runtime-session")
        assert first is not None and await service.mark_started(first.id)
        report = await RecoveryService(db).recover_after_restart()
        pending = await service.next_pending("runtime-session")
        events = await EventRepository(db).list_for_session("runtime-session")
        assert await manager.resume_queued_after_restart() == 1
        await manager.wait("runtime-session")
    finally:
        await manager.shutdown()
        await db.close()

    assert report.interrupted_instructions == 1
    assert pending is not None and pending.message_event_id != first.message_event_id
    assert any(event.event_type == "error.created" and event.payload["code"] == "instruction_delivery_interrupted" for event in events)
    assert len(provider.requests) == 1
    assert provider.requests[0].messages[-1] == {"role": "user", "content": "Second instruction"}


@pytest.mark.asyncio
async def test_interrupt_supersedes_queued_mention_before_dispatch(temporary_sqlite_db) -> None:
    db = await get_db()
    manager = SessionRuntimeManager(publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(db)
        await _running(db)
        builder = (await SessionConfigurationService(db).current("runtime-session")).available_agent_ids[0]
        await _send(db, "cancel-mention", "@builder ignore this", [builder])
        await CommandProcessor(db).process("runtime-session", parse_session_command({
            "commandId": "interrupt-builder", "type": "participant.interrupt",
            "payload": {"participantId": builder, "reasonSummary": "Human stopped this participant."},
        }))
        await manager.start("runtime-session", recovery=True)
        await manager.wait("runtime-session")
        async with db.execute("SELECT state FROM participant_instructions") as cursor:
            state = (await cursor.fetchone())["state"]
        async with db.execute("SELECT COUNT(*) AS total FROM assignments") as cursor:
            assignments = (await cursor.fetchone())["total"]
    finally:
        await manager.shutdown()
        await db.close()

    assert state == "superseded"
    assert assignments == 0


@pytest.mark.asyncio
async def test_paused_reply_waits_for_resume_and_terminal_message_is_rejected(temporary_sqlite_db) -> None:
    db = await get_db()
    provider = ScriptedProvider(((StructuredOutput({
        "type": "final", "finalSummary": "Reply handled after resume.", "evidenceReferences": ["reply"],
    }),),))

    async def resolver(_profile_id: str, _model_id: str):
        return provider

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await _session(db)
        await _running(db)
        await EventRepository(db).append(
            event_id="paused-for-reply", session_id="runtime-session", event_type="session.status_changed",
            actor_id="system", payload={"status": "paused", "reasonSummary": "Waiting for input."}, timestamp_ms=_now_ms(),
        )
        await _send(db, "paused-reply", "Proceed after resume")
        await manager.start("runtime-session")
        await manager.wait("runtime-session")
        assert not provider.requests
        async with db.execute("SELECT state FROM participant_instructions") as cursor:
            assert (await cursor.fetchone())["state"] == "pending"
        await CommandProcessor(db).process("runtime-session", parse_session_command({
            "commandId": "resume-reply", "type": "session.resume", "payload": {},
        }))
        await manager.start("runtime-session")
        await manager.wait("runtime-session")
        with pytest.raises(CommandRejected, match="session_terminal"):
            await _send(db, "too-late", "Should be rejected")
    finally:
        await manager.shutdown()
        await db.close()

    assert len(provider.requests) == 1
