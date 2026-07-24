from __future__ import annotations

import asyncio

import aiosqlite
import pytest

from app.db.database import get_db, transaction
from app.db.repositories import EventRepository, SessionRepository
from app.providers.protocol import ProviderRequest, StructuredOutput
from app.providers.scripted import ScriptedProvider, SlowStream
from app.schemas.session import ApprovalPolicy, RequiredRoleRule, SessionAgentInput, SessionConfigurationInput
from app.schemas.session_commands import parse_session_command
from app.services.command_processor import CommandProcessor
from app.services.coordinator_cycle import CoordinatorCycle
from app.services.participant_instruction_service import ParticipantInstructionService
from app.services.session_configuration_service import SessionConfigurationService


async def coordinator_session(
    database: aiosqlite.Connection, *, required_gate: RequiredRoleRule | None = None,
) -> object:
    await SessionRepository(database).create_legacy_session(
        session_id="coordinator_cycle", name="Coordinator cycle", project_path="workspace",
        task="Route this work", role_configs=[],
    )
    rules = [required_gate] if required_gate is not None else []
    available = ["builder"]
    if required_gate is not None and required_gate.role not in {"builder", "coordinator"}:
        available.append(required_gate.role)
    async with transaction(database):
        return await SessionConfigurationService(database).create_initial(
            session_id="coordinator_cycle",
            agents=[
                SessionAgentInput(id="coordinator", role="coordinator"),
                SessionAgentInput(id="builder", role="builder", capabilities=["workspace.read", "workspace.write"]),
                SessionAgentInput(id="reviewer", role="reviewer", capabilities=["workspace.read"]),
                SessionAgentInput(id="tester", role="tester", capabilities=["test.run"]),
            ],
            coordinator_id="coordinator",
            configuration=SessionConfigurationInput(
                availableAgentIds=available, requiredRoleRules=rules,
                approvalPolicy=ApprovalPolicy(limitResolution="ask_user"),
            ),
            workspace_mode="snapshot", acknowledged_direct_write=False,
        )


def assignment(agent_id: str, *, capabilities: list[str] | None = None) -> dict[str, object]:
    return {
        "type": "assignments", "routingSummary": "Builder is the only relevant available specialist.",
        "assignments": [{
            "proposalId": "proposal-builder", "assigneeAgentId": agent_id,
            "objective": "Inspect and implement the focused change.",
            "acceptanceCriteria": ["Record a concise result."], "operationClass": "mutating",
            "requestedBudget": {}, "requestedCapabilities": capabilities or [],
            "reasonSummary": "This available specialist has the needed capability.",
        }],
    }


@pytest.mark.asyncio
async def test_builder_only_pool_accepts_dynamic_routing_and_skips_irrelevant_roles(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        snapshot = await coordinator_session(database)
        result = await CoordinatorCycle(database).resolve_actions(
            "coordinator_cycle", [assignment(snapshot.available_agent_ids[0])],
        )
    finally:
        await database.close()

    assert result.action is not None and result.action.type == "assignments"
    assert result.visible_summary == "Builder is the only relevant available specialist."


@pytest.mark.asyncio
async def test_coordinator_cannot_select_excluded_agent_or_request_missing_capability(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        snapshot = await coordinator_session(database)
        cycle = CoordinatorCycle(database)
        excluded = await cycle.resolve_actions("coordinator_cycle", [assignment("reviewer")])
        missing_capability = await cycle.resolve_actions(
            "coordinator_cycle", [assignment(snapshot.available_agent_ids[0], capabilities=["test.run"])],
        )
    finally:
        await database.close()

    assert excluded.correction_requested and excluded.error_code == "excluded_agent"
    assert missing_capability.correction_requested and missing_capability.error_code == "missing_capability"


@pytest.mark.asyncio
async def test_malformed_action_gets_exactly_one_correction_then_stops_using_configured_policy(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        snapshot = await coordinator_session(database)
        cycle = CoordinatorCycle(database)
        corrected = await cycle.execute(
            "coordinator_cycle",
            ScriptedProvider(((StructuredOutput({"type": "assignments", "routingSummary": "bad"}),), (StructuredOutput(assignment(snapshot.available_agent_ids[0])),))),
            ProviderRequest("coordinator-request", "fake", ({"role": "user", "content": "Route work"},)),
        )
        repeated = await cycle.execute(
            "coordinator_cycle",
            ScriptedProvider(((StructuredOutput({"type": "permission_grant", "scope": "all"}),), (StructuredOutput({"type": "session_configuration_update"}),))),
            ProviderRequest("coordinator-repeat", "fake", ({"role": "user", "content": "Route work"},)),
        )
    finally:
        await database.close()

    assert corrected.action is not None and corrected.correction_requested
    assert repeated.stopped and repeated.resolution == "ask_user"
    assert repeated.error_code == "malformed_coordinator_action"


@pytest.mark.asyncio
async def test_user_supersede_ends_an_in_flight_coordinator_stream(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        snapshot = await coordinator_session(database)
        cycle = CoordinatorCycle(database)
        provider = ScriptedProvider(((SlowStream(0.05), StructuredOutput(assignment(snapshot.available_agent_ids[0]))),))
        task = asyncio.create_task(cycle.execute(
            "coordinator_cycle", provider,
            ProviderRequest("coordinator-stream", "fake", ({"role": "user", "content": "Route work"},)),
        ))
        await asyncio.sleep(0)
        await CommandProcessor(database).process("coordinator_cycle", parse_session_command({
            "commandId": "superseding-message", "type": "message.send", "payload": {"content": "Use a new approach."},
        }))
        result = await task
    finally:
        await database.close()

    assert result.stopped and result.error_code == "user_superseded"


@pytest.mark.asyncio
async def test_only_one_coordinator_cycle_can_stream_for_a_session(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        snapshot = await coordinator_session(database)
        cycle = CoordinatorCycle(database)
        first = asyncio.create_task(cycle.execute(
            "coordinator_cycle", ScriptedProvider(((SlowStream(0.03), StructuredOutput(assignment(snapshot.available_agent_ids[0]))),)),
            ProviderRequest("first-cycle", "fake", ({"role": "user", "content": "Route work"},)),
        ))
        await asyncio.sleep(0)
        second = await cycle.execute(
            "coordinator_cycle", ScriptedProvider(),
            ProviderRequest("second-cycle", "fake", ({"role": "user", "content": "Route work"},)),
        )
        first_result = await first
    finally:
        await database.close()

    assert second.stopped and second.error_code == "coordinator_cycle_already_active"
    assert first_result.action is not None


@pytest.mark.asyncio
async def test_final_action_cannot_claim_an_unmet_required_gate(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await coordinator_session(database, required_gate=RequiredRoleRule(
            id="review_gate", role="reviewer", applicability="always", successEvidence="approved_review",
        ))
        result = await CoordinatorCycle(database).resolve_actions("coordinator_cycle", [{
            "type": "final", "finalSummary": "Everything is complete.", "evidenceReferences": ["review-evidence"],
        }])
    finally:
        await database.close()

    assert result.correction_requested and result.error_code == "required_gate_unmet"


@pytest.mark.asyncio
async def test_final_action_enforces_a_capability_gate_after_that_capability_was_requested(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await coordinator_session(database, required_gate=RequiredRoleRule(
            id="test_gate", role="tester", applicability="when_capability_used", capability="test.run",
            successEvidence="passing_test_run",
        ))
        await EventRepository(database).append(
            event_id="test-capability-proposal", session_id="coordinator_cycle", event_type="assignment.proposed",
            actor_id="coordinator", timestamp_ms=1,
            payload={
                "proposalId": "test-proposal", "assigneeAgentId": "builder", "objective": "Run tests.",
                "acceptanceCriteria": ["Record results."], "operationClass": "read_only",
                "requestedCapabilities": ["test.run"], "reasonSummary": "Verification needs tests.",
            },
        )
        result = await CoordinatorCycle(database).resolve_actions("coordinator_cycle", [{
            "type": "final", "finalSummary": "Everything is complete.", "evidenceReferences": ["test-evidence"],
        }])
    finally:
        await database.close()

    assert result.correction_requested and result.error_code == "required_gate_unmet"


@pytest.mark.asyncio
async def test_human_messages_are_routed_to_coordinator_or_explicit_participant_instructions(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        snapshot = await coordinator_session(database)
        processor = CommandProcessor(database)
        default = await processor.process("coordinator_cycle", parse_session_command({
            "commandId": "default-message", "type": "message.send", "payload": {"content": "Please continue."},
        }))
        direct = await processor.process("coordinator_cycle", parse_session_command({
            "commandId": "builder-message", "type": "message.send",
            "payload": {"content": "@builder inspect the tests", "mentionIds": ["builder"]},
        }))
        service = ParticipantInstructionService(database)
        coordinator = next(agent["id"] for agent in snapshot.agent_snapshots if agent["role"] == "coordinator")
        builder = snapshot.available_agent_ids[0]
        default_instructions = await service.pending_for("coordinator_cycle", coordinator)
        direct_instructions = await service.pending_for("coordinator_cycle", builder)
        duplicate = await processor.process("coordinator_cycle", parse_session_command({
            "commandId": "default-message", "type": "message.send", "payload": {"content": "Please continue."},
        }))
        async with database.execute("SELECT COUNT(*) AS total FROM participant_instructions WHERE message_event_id = ?", (default.events[0].event_id,)) as cursor:
            duplicate_instruction_count = int((await cursor.fetchone())["total"])
    finally:
        await database.close()

    assert default.events[0].event_type == direct.events[0].event_type == "message.created"
    assert [item.delivery_kind for item in default_instructions] == ["coordinator"]
    assert [item.delivery_kind for item in direct_instructions] == ["explicit_mention"]
    assert duplicate.duplicate and duplicate_instruction_count == 1


@pytest.mark.asyncio
async def test_participant_instructions_cannot_reference_an_event_from_another_session(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await coordinator_session(database)
        await SessionRepository(database).create_legacy_session(
            session_id="other_session", name="Other", project_path="workspace", task="Other task", role_configs=[],
        )
        message = await EventRepository(database).append(
            event_id="source-message", session_id="coordinator_cycle", event_type="message.created", actor_id="human",
            timestamp_ms=1,
            payload={"messageId": "source", "authorId": "human", "authorKind": "human", "content": "Continue."},
        )
        with pytest.raises(aiosqlite.IntegrityError, match="participant instruction references another session"):
            await database.execute(
                """INSERT INTO participant_instructions
                   (id, session_id, message_event_id, participant_id, delivery_kind, state, created_at_ms)
                   VALUES ('cross-session', 'other_session', ?, 'coordinator', 'coordinator', 'pending', 1)""",
                (message.event_id,),
            )
    finally:
        await database.close()
