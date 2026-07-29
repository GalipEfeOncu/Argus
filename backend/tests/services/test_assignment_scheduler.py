"""Scheduler acceptance coverage: durable trees, leases, recovery, and handoffs."""

from __future__ import annotations

import aiosqlite
import pytest

from app.db.database import get_db, transaction
from app.db.repositories import SessionRepository
from app.schemas.coordinator_actions import CoordinatorAssignment
from app.schemas.session import ApprovalPolicy, ExecutionLimits, SessionAgentInput, SessionConfigurationInput
from app.schemas.session_commands import parse_session_command
from app.services.assignment_scheduler import AssignmentScheduler
from app.services.command_processor import CommandProcessor
from app.services.coordinator_cycle import CoordinatorCycle
from app.services.session_configuration_service import SessionConfigurationService


async def scheduler_session(database: aiosqlite.Connection) -> dict[str, str]:
    await database.execute("INSERT INTO projects (id, canonical_path, display_name, git_metadata_json, created_at_ms, updated_at_ms) VALUES ('project_1', '/test/project', 'Project', '{}', 1, 1)")
    await database.commit()
    await SessionRepository(database).create_legacy_session(
        session_id="scheduler_session", name="Scheduler", project_path="workspace", task="Schedule work", role_configs=[], project_id="project_1",
    )
    await database.execute("INSERT INTO workspaces (session_id, project_id, mode, root_path, revision_checksum, created_at_ms, updated_at_ms) VALUES ('scheduler_session', 'project_1', 'snapshot', '/test/workspace', 'base', 1, 1)")
    await database.commit()
    async with transaction(database):
        snapshot = await SessionConfigurationService(database).create_initial(
            session_id="scheduler_session",
            agents=[
                SessionAgentInput(id="coordinator", role="coordinator"),
                SessionAgentInput(id="reader", role="reviewer", capabilities=["workspace.read"]),
                SessionAgentInput(id="writer", role="builder", capabilities=["workspace.read", "workspace.write"]),
            ],
            coordinator_id="coordinator",
            configuration=SessionConfigurationInput(
                availableAgentIds=["reader", "writer"],
                executionLimits=ExecutionLimits(maxParallelReadOnlyAssignments=2, maxAssignmentAttempts=2),
                approvalPolicy=ApprovalPolicy(
                    permissionProfile="autonomous", behavior="preauthorize_session",
                    preauthorizedCapabilities=["workspace.read", "workspace.write"], limitResolution="ask_user",
                ), acknowledgements=["autonomous_permissions"],
            ), workspace_mode="snapshot", acknowledged_direct_write=False,
        )
    await SessionRepository(database).set_status("scheduler_session", "running")
    return {agent["sourceAgentId"]: agent["id"] for agent in snapshot.agent_snapshots}


def proposal(
    proposal_id: str, assignee: str, *, operation: str = "read_only", parent: str | None = None,
    requested_tools: list[str] | None = None,
) -> CoordinatorAssignment:
    capabilities = ["workspace.write"] if operation == "mutating" else ["workspace.read"]
    return CoordinatorAssignment.model_validate({
        "proposalId": proposal_id, "assigneeAgentId": assignee, "parentId": parent,
        "objective": "Complete the bounded scheduler task.", "acceptanceCriteria": ["Persist a concise result."],
        "operationClass": operation, "requestedBudget": {}, "requestedCapabilities": capabilities,
        "requestedTools": requested_tools or [],
        "reasonSummary": "The available specialist has the required capability.",
    })


@pytest.mark.asyncio
async def test_scheduler_persists_assignment_tree_and_duplicate_proposal_once(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await scheduler_session(database)
        scheduler = AssignmentScheduler(database)
        root = await scheduler.accept_coordinator_proposal("scheduler_session", proposal("root", agents["reader"]))
        child = await scheduler.accept_coordinator_proposal("scheduler_session", proposal("child", agents["reader"]), parent_id=root)
        duplicate = await scheduler.accept_coordinator_proposal("scheduler_session", proposal("root", agents["reader"]))
        async with database.execute("SELECT parent_id FROM assignments WHERE id = ?", (child,)) as cursor:
            child_row = await cursor.fetchone()
        async with database.execute("SELECT COUNT(*) AS total FROM assignment_proposals") as cursor:
            proposal_count = int((await cursor.fetchone())["total"])
    finally:
        await database.close()

    assert root == duplicate
    assert child_row["parent_id"] == root
    assert proposal_count == 2


@pytest.mark.asyncio
async def test_rejected_proposals_are_durable_audit_outcomes(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await scheduler_session(database)
        scheduler = AssignmentScheduler(database)
        with pytest.raises(Exception):
            await scheduler.accept_coordinator_proposal("scheduler_session", proposal("rejected", agents["reader"], operation="mutating"))
        async with database.execute("SELECT validation_state, validation_code FROM assignment_proposals WHERE id = 'rejected'") as cursor:
            outcome = await cursor.fetchone()
    finally:
        await database.close()

    assert dict(outcome) == {"validation_state": "rejected", "validation_code": "missing_capability"}


@pytest.mark.asyncio
async def test_scheduler_rejects_tools_outside_the_immutable_agent_allowlist(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await scheduler_session(database)
        with pytest.raises(Exception, match="allow"):
            await AssignmentScheduler(database).accept_coordinator_proposal(
                "scheduler_session", proposal("tool-denied", agents["reader"], requested_tools=["shell_exec"]),
            )
        async with database.execute("SELECT validation_code FROM assignment_proposals WHERE id = 'tool-denied'") as cursor:
            outcome = await cursor.fetchone()
    finally:
        await database.close()

    assert outcome["validation_code"] == "tool_not_allowed"


@pytest.mark.asyncio
async def test_readers_dispatch_in_parallel_and_mutations_are_serialized_by_a_writer_lease(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await scheduler_session(database)
        scheduler = AssignmentScheduler(database)
        await scheduler.accept_coordinator_proposal("scheduler_session", proposal("read-one", agents["reader"]))
        await scheduler.accept_coordinator_proposal("scheduler_session", proposal("read-two", agents["reader"]))
        readers = await scheduler.dispatch_ready("scheduler_session")
        await scheduler.complete_attempt("scheduler_session", readers[0].attempt_id, output_summary="Read complete.")
        await scheduler.complete_attempt("scheduler_session", readers[1].attempt_id, output_summary="Read complete.")
        first = await scheduler.accept_coordinator_proposal("scheduler_session", proposal("write-one", agents["writer"], operation="mutating"))
        second = await scheduler.accept_coordinator_proposal("scheduler_session", proposal("write-two", agents["writer"], operation="mutating"))
        writers = await scheduler.dispatch_ready("scheduler_session")
        await scheduler.complete_attempt("scheduler_session", writers[0].attempt_id, output_summary="First mutation complete.")
        next_writer = await scheduler.dispatch_ready("scheduler_session")
    finally:
        await database.close()

    assert len(readers) == 2 and {item.operation_class for item in readers} == {"read_only"}
    assert len(writers) == 1 and writers[0].assignment_id == first and writers[0].writer_lease_id is not None
    assert len(next_writer) == 1 and next_writer[0].assignment_id == second


@pytest.mark.asyncio
async def test_parent_cancellation_and_orphan_recovery_stop_future_worker_output(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await scheduler_session(database)
        scheduler = AssignmentScheduler(database)
        parent = await scheduler.accept_coordinator_proposal("scheduler_session", proposal("parent", agents["reader"]))
        await scheduler.accept_coordinator_proposal("scheduler_session", proposal("child", agents["reader"]), parent_id=parent)
        running = await scheduler.dispatch_ready("scheduler_session")
        cancelled = await scheduler.cancel_assignment("scheduler_session", parent, reason="Human cancelled the parent work.")
        with pytest.raises(Exception):
            await scheduler.complete_attempt("scheduler_session", running[0].attempt_id, output_summary="Late output")
        mutation = await scheduler.accept_coordinator_proposal("scheduler_session", proposal("orphan", agents["writer"], operation="mutating"))
        writer = (await scheduler.dispatch_ready("scheduler_session"))[0]
        recovered = await scheduler.recover_orphaned_attempts("scheduler_session")
        async with database.execute("SELECT state FROM assignments WHERE id = ?", (mutation,)) as cursor:
            state = (await cursor.fetchone())["state"]
    finally:
        await database.close()

    assert len(cancelled) == 2
    assert recovered == (writer.attempt_id,)
    assert state == "created"


@pytest.mark.asyncio
async def test_participant_interrupt_and_recoverable_failure_queue_only_bounded_retries(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await scheduler_session(database)
        scheduler = AssignmentScheduler(database)
        assignment_id = await scheduler.accept_coordinator_proposal("scheduler_session", proposal("retry", agents["reader"]))
        first_attempt = (await scheduler.dispatch_ready("scheduler_session"))[0]
        assert await scheduler.fail_attempt("scheduler_session", first_attempt.attempt_id, code="provider_disconnected", summary="Temporary provider outage.", recoverable=True)
        retry_attempt = (await scheduler.dispatch_ready("scheduler_session"))[0]
        assert not await scheduler.fail_attempt("scheduler_session", retry_attempt.attempt_id, code="provider_disconnected", summary="Provider unavailable after retry.", recoverable=True)
        other = await scheduler.accept_coordinator_proposal("scheduler_session", proposal("interrupt", agents["reader"]))
        await scheduler.dispatch_ready("scheduler_session")
        interrupted = await scheduler.interrupt_participant("scheduler_session", agents["reader"], reason="Human interrupted this participant.")
    finally:
        await database.close()

    assert assignment_id not in interrupted
    assert other in interrupted


@pytest.mark.asyncio
async def test_specialist_followups_are_handoffs_not_direct_executable_work_and_coordinator_persists_actions(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await scheduler_session(database)
        scheduler = AssignmentScheduler(database)
        source = await scheduler.accept_coordinator_proposal("scheduler_session", proposal("source", agents["reader"]))
        await scheduler.dispatch_ready("scheduler_session")
        handoff = await scheduler.propose_follow_up("scheduler_session", source, proposal("follow-up", agents["reader"]), summary="Please perform a focused follow-up.")
        action = {"type": "assignments", "routingSummary": "Schedule a bounded reader.", "assignments": [proposal("coordinator-action", agents["reader"]).model_dump(by_alias=True, mode="json")]}
        scheduled = await CoordinatorCycle(database).persist_assignments("scheduler_session", action)
        async with database.execute("SELECT state FROM assignment_handoffs WHERE id = ?", (handoff,)) as cursor:
            handoff_state = (await cursor.fetchone())["state"]
    finally:
        await database.close()

    assert handoff_state == "routed_to_coordinator"
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_expired_writer_lease_is_recovered_before_a_new_dispatch(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await scheduler_session(database)
        scheduler = AssignmentScheduler(database)
        first = await scheduler.accept_coordinator_proposal("scheduler_session", proposal("expired-one", agents["writer"], operation="mutating"))
        await scheduler.accept_coordinator_proposal("scheduler_session", proposal("expired-two", agents["writer"], operation="mutating"))
        active = (await scheduler.dispatch_ready("scheduler_session"))[0]
        await database.execute("UPDATE writer_leases SET expires_at_ms = acquired_at_ms + 1 WHERE id = ?", (active.writer_lease_id,))
        await database.execute("UPDATE assignments SET state = 'failed' WHERE id = ?", (first,))
        await database.commit()
        next_assignment = await scheduler.dispatch_ready("scheduler_session")
    finally:
        await database.close()

    assert len(next_assignment) == 1


@pytest.mark.asyncio
async def test_lease_loss_and_canonical_cancel_fence_late_worker_output(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await scheduler_session(database)
        scheduler = AssignmentScheduler(database)
        await scheduler.accept_coordinator_proposal("scheduler_session", proposal("lease-loss", agents["writer"], operation="mutating"))
        active = (await scheduler.dispatch_ready("scheduler_session"))[0]
        await database.execute("UPDATE writer_leases SET expires_at_ms = acquired_at_ms + 1 WHERE id = ?", (active.writer_lease_id,))
        await database.commit()
        with pytest.raises(Exception):
            await scheduler.complete_attempt("scheduler_session", active.attempt_id, output_summary="Late mutation")
        await scheduler.recover_orphaned_attempts("scheduler_session")
        retry = (await scheduler.dispatch_ready("scheduler_session"))[0]
        cancelled = await CommandProcessor(database).process("scheduler_session", parse_session_command({
            "commandId": "cancel-active-work", "type": "session.cancel", "payload": {"reasonSummary": "Stop now."},
        }))
        with pytest.raises(Exception):
            await scheduler.complete_attempt("scheduler_session", retry.attempt_id, output_summary="Late output")
        duplicate = await CommandProcessor(database).process("scheduler_session", parse_session_command({
            "commandId": "cancel-active-work", "type": "session.cancel", "payload": {"reasonSummary": "Stop now."},
        }))
    finally:
        await database.close()

    assert any(event.event_type == "assignment.cancelled" for event in cancelled.events)
    assert duplicate.duplicate and len(duplicate.events) == len(cancelled.events)


@pytest.mark.asyncio
async def test_session_preauthorization_is_persisted_for_scheduler_policy_checks(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await scheduler_session(database)
        async with database.execute("SELECT capability, decision, grant_scope FROM approvals WHERE session_id = 'scheduler_session' ORDER BY capability") as cursor:
            grants = [dict(row) for row in await cursor.fetchall()]
    finally:
        await database.close()

    assert grants == [
        {"capability": "workspace.read", "decision": "granted", "grant_scope": "session"},
        {"capability": "workspace.write", "decision": "granted", "grant_scope": "session"},
    ]


def test_static_agent_graph_websocket_route_is_removed() -> None:
    from app.api.websocket import router

    paths = {getattr(route, "path", None) for route in router.routes}

    assert "/ws/session/{session_id}" not in paths
    assert "/ws/sessions/{session_id}" in paths
