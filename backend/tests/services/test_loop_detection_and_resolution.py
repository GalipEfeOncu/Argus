"""Phase 4.3 loop fingerprint, follow-up, and reached-limit resolution coverage."""

from __future__ import annotations

import aiosqlite
import pytest

from app.db.database import get_db, transaction
from app.db.repositories import EventRepository, SessionRepository
from app.providers.protocol import ProviderRequest, StructuredOutput
from app.providers.scripted import ScriptedProvider
from app.schemas.coordinator_actions import CoordinatorAssignment
from app.schemas.session import ApprovalPolicy, ExecutionLimits, SessionAgentInput, SessionConfigurationInput
from app.schemas.session_commands import parse_session_command
from app.services.assignment_scheduler import AssignmentScheduler, SchedulerRejected
from app.services.command_processor import CommandProcessor, CommandRejected
from app.services.limit_resolution_service import LimitResolutionService
from app.services.loop_detection_service import LoopDetectionService
from app.services.coordinator_cycle import CoordinatorCycle
from app.services.session_configuration_service import SessionConfigurationService


async def loop_session(database: aiosqlite.Connection, *, mode: str = "ask_user") -> dict[str, str]:
    await database.execute("INSERT INTO projects (id, canonical_path, display_name, git_metadata_json, created_at_ms, updated_at_ms) VALUES ('loop_project', '/test/loop', 'Loop', '{}', 1, 1)")
    await database.commit()
    await SessionRepository(database).create_legacy_session(
        session_id="loop_session", name="Loop", project_path="workspace", task="Avoid loops", role_configs=[], project_id="loop_project",
    )
    await database.execute("INSERT INTO workspaces (session_id, project_id, mode, root_path, revision_checksum, created_at_ms, updated_at_ms) VALUES ('loop_session', 'loop_project', 'snapshot', '/test/loop-workspace', 'base', 1, 1)")
    await database.commit()
    async with transaction(database):
        snapshot = await SessionConfigurationService(database).create_initial(
            session_id="loop_session",
            agents=[
                SessionAgentInput(id="coordinator", role="coordinator"),
                SessionAgentInput(id="reviewer", role="reviewer", capabilities=["workspace.read"]),
                SessionAgentInput(id="writer_a", role="builder", capabilities=["workspace.write"]),
                SessionAgentInput(id="writer_b", role="builder", capabilities=["workspace.write"]),
            ], coordinator_id="coordinator",
            configuration=SessionConfigurationInput(
                availableAgentIds=["reviewer", "writer_a", "writer_b"], executionLimits=ExecutionLimits(maxRevisionsPerFinding=1),
                approvalPolicy=ApprovalPolicy(permissionProfile="autonomous", behavior="preauthorize_session", preauthorizedCapabilities=["workspace.read", "workspace.write"], limitResolution=mode), acknowledgements=["autonomous_permissions"],
            ), workspace_mode="snapshot", acknowledged_direct_write=False,
        )
    await SessionRepository(database).set_status("loop_session", "running")
    return {agent["sourceAgentId"]: agent["id"] for agent in snapshot.agent_snapshots}


def mutating_proposal(agent_id: str, fingerprint: str) -> CoordinatorAssignment:
    return CoordinatorAssignment.model_validate({
        "proposalId": f"followup-{agent_id}", "assigneeAgentId": agent_id, "objective": "Address one normalized finding.",
        "acceptanceCriteria": ["Record the result."], "operationClass": "mutating", "requestedBudget": {},
        "requestedCapabilities": ["workspace.write"], "reasonSummary": "This is a bounded follow-up.",
        "findingFingerprint": fingerprint,
    })


def test_review_fingerprint_uses_stable_structure_not_prose_or_secret_values() -> None:
    first = LoopDetectionService.finding_fingerprint({"category": "correctness", "path": "SRC/App.py", "lineAnchor": 12, "message": "Leaked sk-abcdefghijklmnop"})
    reworded = LoopDetectionService.finding_fingerprint({"category": "correctness", "path": "src/app.py", "lineAnchor": 12, "message": "Entirely different prose"})
    distinct = LoopDetectionService.finding_fingerprint({"category": "correctness", "path": "src/app.py", "lineAnchor": 19})

    assert first == reworded
    assert first != distinct
    assert "sk-" not in first


@pytest.mark.asyncio
async def test_accepted_mutating_follow_up_counts_only_the_same_known_finding(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await loop_session(database)
        loops = LoopDetectionService(database)
        fingerprint = LoopDetectionService.finding_fingerprint({"category": "correctness", "path": "src/app.py", "lineAnchor": 12})
        async with transaction(database):
            await loops._record_in_transaction("loop_session", "review_finding", fingerprint, assignment_id=None)
        assignment_id = await AssignmentScheduler(database).accept_coordinator_proposal("loop_session", mutating_proposal(agents["writer_a"], fingerprint))
        with pytest.raises(SchedulerRejected) as rejected:
            await AssignmentScheduler(database).accept_coordinator_proposal("loop_session", mutating_proposal(agents["writer_b"], "0" * 64))
        async with database.execute("SELECT scope_id, consumed_real FROM limit_counters WHERE session_id = 'loop_session' AND counter_kind = 'revisions'") as cursor:
            counter = await cursor.fetchone()
        async with database.execute("SELECT assignment_id FROM finding_follow_ups WHERE session_id = 'loop_session'") as cursor:
            linked = await cursor.fetchone()
    finally:
        await database.close()

    assert rejected.value.code == "unknown_finding_fingerprint"
    assert counter["scope_id"] == fingerprint and counter["consumed_real"] == 1
    assert linked["assignment_id"] == assignment_id


@pytest.mark.asyncio
async def test_repeated_no_progress_creates_one_human_decision_and_rejects_unknown_replay(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await loop_session(database)
        loops = LoopDetectionService(database)
        async with transaction(database):
            first = await loops.record_no_progress_in_transaction("loop_session", None, "same-workspace", "same-diff")
            second = await loops.record_no_progress_in_transaction("loop_session", None, "same-workspace", "same-diff")
            request_id = await LimitResolutionService(database).request_latest_in_transaction(
                "loop_session", counter="no_progress", scope_id="loop_session", assignment_id=None, fingerprint=second.fingerprint,
                reason_summary="No workspace progress.",
            )
            duplicate = await LimitResolutionService(database).request_latest_in_transaction(
                "loop_session", counter="no_progress", scope_id="loop_session", assignment_id=None, fingerprint=second.fingerprint,
            )
        async with database.execute("SELECT decision_id, state FROM limit_resolution_requests WHERE id = ?", (request_id,)) as cursor:
            request = await cursor.fetchone()
        with pytest.raises(CommandRejected, match="limit_decision_not_requested"):
            await CommandProcessor(database).process("loop_session", parse_session_command({
                "commandId": "unknown-decision", "type": "decision.resolve", "payload": {"decisionId": "unknown", "choice": "stop"},
            }))
        outcome = await CommandProcessor(database).process("loop_session", parse_session_command({
            "commandId": "stop-loop", "type": "decision.resolve", "payload": {"decisionId": request["decision_id"], "choice": "stop"},
        }))
    finally:
        await database.close()

    assert first.occurrence_count == 1 and second.occurrence_count == 2
    assert request_id == duplicate and request["state"] == "pending"
    assert [event.event_type for event in outcome.events] == ["decision.recorded", "session.status_changed"]


@pytest.mark.asyncio
async def test_coordinator_limit_decision_is_single_structured_tool_free_turn_and_stops_on_malformed(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await loop_session(database, mode="coordinator_decides")
        source = await EventRepository(database).append(
            event_id="limit-source", session_id="loop_session", event_type="limit.reached", actor_id="system", timestamp_ms=1,
            payload={"counter": "repeated_failure", "scopeId": "loop_session", "current": 2, "threshold": 2, "hard": True, "resolution": "coordinator_decides", "fingerprint": "f" * 64, "occurrenceCount": 2},
        )
        async with transaction(database):
            await LimitResolutionService(database).request_for_event_in_transaction(
                "loop_session", source.event_id, counter="repeated_failure", scope_id="loop_session", assignment_id=None,
                fingerprint="f" * 64, reason_summary="Repeated failure.",
            )
        result = await LimitResolutionService(database).execute_coordinator_decision(
            "loop_session", ScriptedProvider(((StructuredOutput({"choice": "not_allowed", "reasonSummary": "bad"}),),)),
            ProviderRequest("limit-decision", "fake", ({"role": "system", "content": "Choose."},)),
        )
        async with database.execute("SELECT state FROM limit_resolution_requests") as cursor:
            state = (await cursor.fetchone())["state"]
    finally:
        await database.close()

    assert result is None and state == "stopped"


@pytest.mark.asyncio
async def test_human_cancellation_wins_over_a_pending_limit_decision(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await loop_session(database)
        source = await EventRepository(database).append(
            event_id="cancel-source", session_id="loop_session", event_type="limit.reached", actor_id="system", timestamp_ms=1,
            payload={"counter": "no_progress", "scopeId": "loop_session", "current": 2, "threshold": 2, "hard": True, "resolution": "ask_user", "fingerprint": "c" * 64, "occurrenceCount": 2},
        )
        async with transaction(database):
            request_id = await LimitResolutionService(database).request_for_event_in_transaction(
                "loop_session", source.event_id, counter="no_progress", scope_id="loop_session", assignment_id=None,
                fingerprint="c" * 64, reason_summary="No progress.",
            )
        await CommandProcessor(database).process("loop_session", parse_session_command({
            "commandId": "cancel-limit", "type": "session.cancel", "payload": {"reasonSummary": "Human stopped."},
        }))
        async with database.execute("SELECT state FROM limit_resolution_requests WHERE id = ?", (request_id,)) as cursor:
            state = (await cursor.fetchone())["state"]
    finally:
        await database.close()

    assert state == "cancelled"


@pytest.mark.asyncio
async def test_user_limit_partial_choice_requires_a_second_explicit_partial_acceptance(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await loop_session(database)
        source = await EventRepository(database).append(
            event_id="partial-source", session_id="loop_session", event_type="limit.reached", actor_id="system", timestamp_ms=1,
            payload={"counter": "no_progress", "scopeId": "loop_session", "current": 2, "threshold": 2, "hard": True, "resolution": "ask_user", "fingerprint": "d" * 64, "occurrenceCount": 2},
        )
        async with transaction(database):
            request_id = await LimitResolutionService(database).request_for_event_in_transaction(
                "loop_session", source.event_id, counter="no_progress", scope_id="loop_session", assignment_id=None,
                fingerprint="d" * 64, reason_summary="No progress.",
            )
        async with database.execute("SELECT decision_id FROM limit_resolution_requests WHERE id = ?", (request_id,)) as cursor:
            decision_id = (await cursor.fetchone())["decision_id"]
        first = await CommandProcessor(database).process("loop_session", parse_session_command({
            "commandId": "choose-partial", "type": "decision.resolve", "payload": {"decisionId": decision_id, "choice": "deliver_partial"},
        }))
        async with database.execute("SELECT state FROM limit_resolution_requests WHERE id = ?", (request_id,)) as cursor:
            state = (await cursor.fetchone())["state"]
        partial = next(event.payload["decisionId"] for event in first.events if event.event_type == "decision.requested")
        second = await CommandProcessor(database).process("loop_session", parse_session_command({
            "commandId": "accept-partial", "type": "decision.resolve", "payload": {"decisionId": partial, "choice": "deliver_partial"},
        }))
    finally:
        await database.close()

    assert state == "resolved"
    assert [event.event_type for event in first.events] == ["decision.recorded", "decision.requested", "session.status_changed"]
    assert second.events[-1].payload["status"] == "completed_partial"
