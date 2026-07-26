"""Phase 4.2 coverage for durable limit accounting and reservation boundaries."""

from __future__ import annotations

import asyncio

import aiosqlite
import pytest

from app.db.database import get_db, transaction
from app.db.repositories import EventRepository, SessionRepository
from app.schemas.session import ExecutionLimits, SessionAgentInput, SessionConfigurationInput
from app.services.assignment_scheduler import AssignmentScheduler
from app.services.budget_counter_service import BudgetCounterService, BudgetExceeded
from app.services.session_configuration_service import SessionConfigurationService


async def budget_session(database: aiosqlite.Connection, limits: ExecutionLimits) -> dict[str, str]:
    await SessionRepository(database).create_legacy_session(
        session_id="budget_session", name="Budget", project_path="workspace", task="Count bounded work", role_configs=[],
    )
    async with transaction(database):
        snapshot = await SessionConfigurationService(database).create_initial(
            session_id="budget_session",
            agents=[
                SessionAgentInput(id="coordinator", role="coordinator"),
                SessionAgentInput(id="reader", role="reviewer", capabilities=["workspace.read"]),
            ],
            coordinator_id="coordinator",
            configuration=SessionConfigurationInput(availableAgentIds=["reader"], executionLimits=limits),
            workspace_mode="snapshot", acknowledged_direct_write=False,
        )
    return {agent["sourceAgentId"]: agent["id"] for agent in snapshot.agent_snapshots}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ceiling", "first_allowed", "second_allowed"),
    [(0, False, False), (1, True, False), (2, True, True), (None, True, True)],
)
async def test_zero_one_finite_and_unlimited_ceilings(temporary_sqlite_db, ceiling, first_allowed, second_allowed) -> None:
    database = await get_db()
    try:
        await budget_session(database, ExecutionLimits(maxToolCallsPerAssignment=ceiling))
        budgets = BudgetCounterService(database)
        outcomes: list[bool] = []
        for _ in range(2):
            try:
                await budgets.reserve("budget_session", counter="tool_calls", scope_type="assignment", scope_id="asn_1")
            except BudgetExceeded:
                outcomes.append(False)
            else:
                outcomes.append(True)
    finally:
        await database.close()

    assert outcomes == [first_allowed, second_allowed]


@pytest.mark.asyncio
async def test_soft_warning_is_emitted_once_at_the_configured_ratio(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await budget_session(database, ExecutionLimits(maxToolCallsPerAssignment=10, softWarningRatio=0.8))
        budgets = BudgetCounterService(database)
        await budgets.reserve("budget_session", counter="tool_calls", scope_type="assignment", scope_id="asn_1", amount=8)
        await budgets.reserve("budget_session", counter="tool_calls", scope_type="assignment", scope_id="asn_1")
        events = await EventRepository(database).list_for_session("budget_session")
    finally:
        await database.close()

    warnings = [event for event in events if event.event_type == "limit.warning"]
    assert len(warnings) == 1
    assert warnings[0].payload["current"] == 8


@pytest.mark.asyncio
async def test_hard_limit_event_is_committed_before_a_standalone_rejection(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await budget_session(database, ExecutionLimits(maxToolCallsPerAssignment=0))
        with pytest.raises(BudgetExceeded):
            await BudgetCounterService(database).record_tool_call("budget_session", "missing_assignment")
        events = await EventRepository(database).list_for_session("budget_session")
    finally:
        await database.close()

    reached = [event for event in events if event.event_type == "limit.reached"]
    assert len(reached) == 1
    assert reached[0].payload["counter"] == "tool_calls"


@pytest.mark.asyncio
async def test_concurrent_read_only_reservations_cannot_overbook_a_slot(temporary_sqlite_db) -> None:
    setup = await get_db()
    try:
        await budget_session(setup, ExecutionLimits(maxParallelReadOnlyAssignments=1))
    finally:
        await setup.close()
    first, second = await asyncio.gather(get_db(), get_db())
    try:
        async def reserve(connection: aiosqlite.Connection, assignment: str) -> bool:
            try:
                await BudgetCounterService(connection).reserve(
                    "budget_session", counter="parallel_read_only_assignments", scope_type="session",
                    scope_id="budget_session", hold=True,
                )
            except BudgetExceeded:
                return False
            return True

        outcomes = await asyncio.gather(reserve(first, "asn_1"), reserve(second, "asn_2"))
    finally:
        await first.close()
        await second.close()

    assert sorted(outcomes) == [False, True]


@pytest.mark.asyncio
async def test_consumed_counter_survives_restart_and_does_not_grant_a_retry(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await budget_session(database, ExecutionLimits(maxAssignmentAttempts=1))
        await BudgetCounterService(database).reserve(
            "budget_session", counter="assignment_attempts", scope_type="assignment", scope_id="asn_1",
        )
    finally:
        await database.close()
    restarted = await get_db()
    try:
        with pytest.raises(BudgetExceeded):
            await BudgetCounterService(restarted).reserve(
                "budget_session", counter="assignment_attempts", scope_type="assignment", scope_id="asn_1",
            )
    finally:
        await restarted.close()


@pytest.mark.asyncio
async def test_provider_usage_correction_and_unavailable_cost_are_normalized(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await budget_session(database, ExecutionLimits(maxSessionTokens=100, maxSessionCost=3))
        await SessionRepository(database).set_status("budget_session", "running")
        scheduler = AssignmentScheduler(database)
        from app.schemas.coordinator_actions import CoordinatorAssignment
        assignment_id = await scheduler.accept_coordinator_proposal("budget_session", CoordinatorAssignment.model_validate({
            "proposalId": "usage", "assigneeAgentId": agents["reader"], "objective": "Read only.",
            "acceptanceCriteria": ["Report usage."], "operationClass": "read_only", "requestedBudget": {},
            "requestedCapabilities": [], "reasonSummary": "Need a bounded attempt.",
        }))
        await scheduler.dispatch_ready("budget_session")
        budgets = BudgetCounterService(database)
        await budgets.record_provider_usage("budget_session", assignment_id, input_tokens=10, output_tokens=5,
                                            normalized_cost=2.0, duration_ms=10, cost_uncertainty="estimated")
        await budgets.record_provider_usage("budget_session", assignment_id, input_tokens=8, output_tokens=4,
                                            normalized_cost=1.25, duration_ms=12, cost_uncertainty="exact")
        await budgets.record_provider_usage("budget_session", assignment_id, input_tokens=8, output_tokens=4,
                                            normalized_cost=None, duration_ms=12, cost_uncertainty="unavailable")
        async with database.execute(
            "SELECT counter_kind, consumed_real FROM limit_counters WHERE session_id = 'budget_session' ORDER BY counter_kind"
        ) as cursor:
            counters = {row["counter_kind"]: row["consumed_real"] for row in await cursor.fetchall()}
        events = await EventRepository(database).list_for_session("budget_session")
    finally:
        await database.close()

    assert counters["tokens"] == 12
    assert counters["cost"] == 1.25
    assert [event.payload["costUncertainty"] for event in events if event.event_type == "usage.updated"] == ["estimated", "exact", "unavailable"]
    assert [event.payload["normalizedCost"] for event in events if event.event_type == "usage.updated"][-1] is None


@pytest.mark.asyncio
async def test_wall_clock_excludes_paused_time_and_rejects_only_excess_work(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await budget_session(database, ExecutionLimits(maxWallClockSeconds=5, maxToolCallsPerAssignment=None))
        events = EventRepository(database)
        await events.append(event_id="run_1", session_id="budget_session", event_type="session.status_changed", actor_id="system", payload={"status": "running"}, timestamp_ms=1_000)
        await events.append(event_id="pause_1", session_id="budget_session", event_type="session.status_changed", actor_id="human", payload={"status": "paused"}, timestamp_ms=6_000)
        # The long paused interval is deliberately absent from the durable clock.
        await BudgetCounterService(database).reserve("budget_session", counter="tool_calls", scope_type="assignment", scope_id="asn_1")
        await events.append(event_id="run_2", session_id="budget_session", event_type="session.status_changed", actor_id="human", payload={"status": "running"}, timestamp_ms=100_000)
        await events.append(event_id="pause_2", session_id="budget_session", event_type="session.status_changed", actor_id="human", payload={"status": "paused"}, timestamp_ms=102_000)
        with pytest.raises(BudgetExceeded):
            await BudgetCounterService(database).reserve("budget_session", counter="tool_calls", scope_type="assignment", scope_id="asn_1")
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_capacity_is_consumed_on_start_then_released_by_a_cancel_command(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await budget_session(database, ExecutionLimits(maxParallelReadOnlyAssignments=1))
        await SessionRepository(database).set_status("budget_session", "running")
        scheduler = AssignmentScheduler(database)
        from app.schemas.coordinator_actions import CoordinatorAssignment
        from app.schemas.session_commands import parse_session_command
        from app.services.command_processor import CommandProcessor
        make = lambda proposal_id: CoordinatorAssignment.model_validate({
            "proposalId": proposal_id, "assigneeAgentId": agents["reader"], "objective": "Read only.",
            "acceptanceCriteria": ["Report."], "operationClass": "read_only", "requestedBudget": {},
            "requestedCapabilities": [], "reasonSummary": "Bounded reader.",
        })
        first = await scheduler.accept_coordinator_proposal("budget_session", make("first"))
        await scheduler.dispatch_ready("budget_session")
        async with database.execute("SELECT state FROM limit_reservations WHERE assignment_id = ?", (first,)) as cursor:
            state = (await cursor.fetchone())["state"]
        await CommandProcessor(database).process("budget_session", parse_session_command({
            "commandId": "cancel-reader", "type": "participant.interrupt",
            "payload": {"participantId": agents["reader"], "reasonSummary": "Stop."},
        }))
        second = await scheduler.accept_coordinator_proposal("budget_session", make("second"))
        started = await scheduler.dispatch_ready("budget_session")
    finally:
        await database.close()

    assert state == "consumed"
    assert started[0].assignment_id == second


@pytest.mark.asyncio
async def test_fractional_cost_is_considered_when_lowering_configuration(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await budget_session(database, ExecutionLimits(maxSessionCost=3))
        await SessionRepository(database).set_status("budget_session", "running")
        scheduler = AssignmentScheduler(database)
        from app.schemas.coordinator_actions import CoordinatorAssignment
        from app.schemas.session_commands import SessionConfigurationPatch
        assignment_id = await scheduler.accept_coordinator_proposal("budget_session", CoordinatorAssignment.model_validate({
            "proposalId": "cost", "assigneeAgentId": agents["reader"], "objective": "Read.",
            "acceptanceCriteria": ["Report."], "operationClass": "read_only", "requestedBudget": {},
            "requestedCapabilities": [], "reasonSummary": "Bounded reader.",
        }))
        await scheduler.dispatch_ready("budget_session")
        await BudgetCounterService(database).record_provider_usage("budget_session", assignment_id, input_tokens=1, output_tokens=1, normalized_cost=1.25, duration_ms=1, cost_uncertainty="exact")
        service = SessionConfigurationService(database)
        current = await service.current("budget_session")
        consequences = await service.consequences("budget_session", current, SessionConfigurationPatch(executionLimits={"maxSessionCost": 1.1}))
    finally:
        await database.close()

    assert consequences.requires_confirmation
