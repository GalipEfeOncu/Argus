"""Phase 4.1 acceptance coverage for deterministic required-role gates."""

from __future__ import annotations

import json

import aiosqlite
import pytest

from app.db.database import get_db, transaction
from app.db.repositories import SessionRepository
from app.providers.protocol import ProviderRequest, StructuredOutput
from app.providers.scripted import ScriptedProvider
from app.schemas.coordinator_actions import CoordinatorAssignment, PartialAction
from app.schemas.session import ApprovalPolicy, RequiredRoleRule, SessionAgentInput, SessionConfigurationInput
from app.schemas.session_commands import SessionConfigurationPatch, parse_session_command
from app.services.assignment_scheduler import AssignmentScheduler, SchedulerRejected
from app.services.command_processor import CommandProcessor, CommandRejected
from app.services.coordinator_cycle import CoordinatorCycle
from app.services.gate_engine import GateEngine
from app.services.session_configuration_service import ConfigurationError, SessionConfigurationService


async def gate_session(database: aiosqlite.Connection, rules: list[RequiredRoleRule], *, custom: bool = False) -> dict[str, str]:
    await database.execute("INSERT INTO projects (id, canonical_path, display_name, git_metadata_json, created_at_ms, updated_at_ms) VALUES ('gate_project', '/test/gates', 'Gates', '{}', 1, 1)")
    await database.commit()
    await SessionRepository(database).create_legacy_session(
        session_id="gate_session", name="Gates", project_path="workspace", task="Verify gates", role_configs=[], project_id="gate_project",
    )
    await database.execute("INSERT INTO workspaces (session_id, project_id, mode, root_path, revision_checksum, created_at_ms, updated_at_ms) VALUES ('gate_session', 'gate_project', 'snapshot', '/test/gate-workspace', 'base', 1, 1)")
    await database.commit()
    agents = [
        SessionAgentInput(id="coordinator", role="coordinator"),
        SessionAgentInput(id="planner", role="planner"),
        SessionAgentInput(id="builder", role="builder"),
        SessionAgentInput(id="ui", role="ui_agent"),
        SessionAgentInput(id="reviewer", role="reviewer", capabilities=["workspace.read"]),
        SessionAgentInput(id="tester", role="tester", capabilities=["test.run"]),
    ]
    if custom:
        agents.append(SessionAgentInput(
            id="custom", role="security", evidenceSchema={
                "type": "object", "required": ["approved"], "properties": {"approved": {"type": "boolean"}},
                "additionalProperties": False,
            },
        ))
    async with transaction(database):
        snapshot = await SessionConfigurationService(database).create_initial(
            session_id="gate_session", agents=agents, coordinator_id="coordinator",
            configuration=SessionConfigurationInput(
                availableAgentIds=[agent.id for agent in agents if agent.id != "coordinator"], requiredRoleRules=rules,
                approvalPolicy=ApprovalPolicy(permissionProfile="autonomous", behavior="preauthorize_session", preauthorizedCapabilities=["test.run"]),
                acknowledgements=["autonomous_permissions"],
            ), workspace_mode="snapshot", acknowledged_direct_write=False,
        )
    await SessionRepository(database).set_status("gate_session", "running")
    return {agent["sourceAgentId"]: agent["id"] for agent in snapshot.agent_snapshots}


def work(proposal_id: str, agent_id: str) -> CoordinatorAssignment:
    return CoordinatorAssignment.model_validate({
        "proposalId": proposal_id, "assigneeAgentId": agent_id, "objective": "Produce required structured evidence.",
        "acceptanceCriteria": ["Return deterministic evidence."], "operationClass": "read_only",
        "requestedBudget": {}, "requestedCapabilities": [], "reasonSummary": "Required role evidence is needed.",
    })


def test_required_role_without_available_eligible_agent_is_rejected() -> None:
    configuration = SessionConfigurationInput(requiredRoleRules=[
        RequiredRoleRule(id="review", role="reviewer", applicability="always", successEvidence="approved_review"),
    ])

    with pytest.raises(ConfigurationError, match="Required role 'reviewer' has no eligible available agent"):
        SessionConfigurationService._validate(
            [SessionAgentInput(id="coordinator", role="coordinator")], "coordinator", configuration, "snapshot",
            acknowledged_direct_write=False,
        )


async def complete(database: aiosqlite.Connection, agent_id: str, evidence: dict[str, object], proposal_id: str) -> None:
    scheduler = AssignmentScheduler(database)
    await scheduler.accept_coordinator_proposal("gate_session", work(proposal_id, agent_id))
    attempt = next(item for item in await scheduler.dispatch_ready("gate_session") if item.assignment_id)
    await scheduler.complete_attempt("gate_session", attempt.attempt_id, output_summary="Structured evidence recorded.", evidence=[evidence])


@pytest.mark.asyncio
async def test_required_reviewer_and_tester_are_routed_before_final_success(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await gate_session(database, [
            RequiredRoleRule(id="review", role="reviewer", applicability="always", successEvidence="approved_review"),
            RequiredRoleRule(id="test", role="tester", applicability="always", successEvidence="passing_test_run"),
        ])
        result = await CoordinatorCycle(database).resolve_actions("gate_session", [{
            "type": "final", "finalSummary": "Done.", "evidenceReferences": ["none"],
        }])
        async with database.execute("SELECT agent.role FROM assignments JOIN session_agents agent ON agent.id = assignments.assignee_session_agent_id ORDER BY assignments.created_at_ms") as cursor:
            roles = [row["role"] for row in await cursor.fetchall()]
    finally:
        await database.close()

    assert result.error_code == "required_gate_unmet"
    assert roles == ["reviewer", "tester"]


@pytest.mark.asyncio
async def test_conditional_gate_is_not_applicable_without_changes(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await gate_session(database, [RequiredRoleRule(id="review", role="reviewer", applicability="when_changes", successEvidence="approved_review")])
        result = await CoordinatorCycle(database).resolve_actions("gate_session", [{
            "type": "final", "finalSummary": "No workspace changes were needed.", "evidenceReferences": ["summary"],
        }])
    finally:
        await database.close()

    assert result.action is not None and result.action.type == "final"


@pytest.mark.asyncio
async def test_capability_gate_uses_accepted_proposals_not_rejected_model_output(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await gate_session(database, [RequiredRoleRule(
            id="test", role="tester", applicability="when_capability_used", capability="test.run", successEvidence="passing_test_run",
        )])
        rejected = CoordinatorAssignment.model_validate({
            **work("rejected-capability", agents["builder"]).model_dump(by_alias=True), "requestedCapabilities": ["test.run"],
        })
        with pytest.raises(SchedulerRejected):
            await AssignmentScheduler(database).accept_coordinator_proposal("gate_session", rejected)
        assert (await GateEngine(database).states("gate_session"))[0].status == "not_applicable"
        accepted = CoordinatorAssignment.model_validate({
            **work("accepted-capability", agents["tester"]).model_dump(by_alias=True), "requestedCapabilities": ["test.run"],
        })
        await AssignmentScheduler(database).accept_coordinator_proposal("gate_session", accepted)
        assert (await GateEngine(database).states("gate_session"))[0].status == "pending"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_distinct_pending_gates_with_the_same_evidence_each_receive_work(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await gate_session(database, [
            RequiredRoleRule(id="review_one", role="reviewer", applicability="always", successEvidence="approved_review"),
            RequiredRoleRule(id="review_two", role="reviewer", applicability="always", successEvidence="approved_review"),
        ])
        queued = await GateEngine(database).route_unsatisfied("gate_session")
    finally:
        await database.close()

    assert len(queued) == 2


@pytest.mark.asyncio
async def test_invalid_model_prose_and_stale_review_evidence_do_not_satisfy_gate(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await gate_session(database, [RequiredRoleRule(id="review", role="reviewer", applicability="always", successEvidence="approved_review")])
        await complete(database, agents["reviewer"], {"kind": "approved_review", "summary": "Looks good.", "artifactIds": []}, "prose")
        async with database.execute("SELECT validation_state FROM gate_evidence") as cursor:
            prose_state = (await cursor.fetchone())["validation_state"]
        await complete(database, agents["reviewer"], {
            "kind": "approved_review", "summary": "Approved at base.", "artifactIds": [],
            "data": {"verdict": "approved", "findings": [], "workspaceRevision": "base"},
        }, "review-base")
        async with transaction(database):
            await database.execute("UPDATE workspaces SET revision_checksum = 'next' WHERE session_id = 'gate_session'")
            await GateEngine(database).invalidate_after_mutation("gate_session", "next")
        async with database.execute("SELECT COUNT(*) AS total FROM gate_evidence WHERE invalidated_at_ms IS NOT NULL") as cursor:
            stale = int((await cursor.fetchone())["total"])
    finally:
        await database.close()

    assert prose_state == "invalid"
    assert stale == 1


@pytest.mark.asyncio
async def test_minimum_completions_and_custom_schema_are_deterministically_enforced(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await gate_session(database, [
            RequiredRoleRule(id="reviews", role="reviewer", applicability="always", successEvidence="approved_review", minimumCompletions=2),
            RequiredRoleRule(id="security", role="security", applicability="always", successEvidence="security_approved"),
        ], custom=True)
        review = {"kind": "approved_review", "summary": "Approved.", "artifactIds": [], "data": {"verdict": "approved", "findings": [], "workspaceRevision": "base"}}
        await complete(database, agents["reviewer"], review, "review-one")
        await complete(database, agents["reviewer"], review, "review-two")
        await complete(database, agents["custom"], {"kind": "security_approved", "summary": "Approved by policy.", "artifactIds": [], "data": {"approved": True}}, "security")
        states = {state.rule["id"]: state.status for state in await GateEngine(database).states("gate_session")}
    finally:
        await database.close()

    assert states == {"reviews": "satisfied", "security": "satisfied"}


@pytest.mark.asyncio
async def test_builtin_role_evidence_schemas_accept_only_structured_contracts(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        agents = await gate_session(database, [
            RequiredRoleRule(id="plan", role="planner", applicability="always", successEvidence="accepted_plan", acceptanceFields=["scope"]),
            RequiredRoleRule(id="build", role="builder", applicability="always", successEvidence="verified_change"),
            RequiredRoleRule(id="ui", role="ui_agent", applicability="always", successEvidence="verified_change"),
            RequiredRoleRule(id="review", role="reviewer", applicability="always", successEvidence="approved_review"),
            RequiredRoleRule(id="test", role="tester", applicability="always", successEvidence="passing_test_run"),
        ])
        await complete(database, agents["planner"], {"kind": "accepted_plan", "summary": "Plan accepted.", "artifactIds": [], "data": {"plan": {"scope": "API", "steps": ["Inspect", "Implement"]}}}, "plan")
        await complete(database, agents["builder"], {"kind": "verified_change", "summary": "Change verified.", "artifactIds": ["diff-builder"], "data": {"changeKind": "diff", "workspaceRevision": "base"}}, "build")
        await complete(database, agents["ui"], {"kind": "verified_change", "summary": "UI change verified.", "artifactIds": ["diff-ui"], "data": {"changeKind": "diff", "workspaceRevision": "base"}}, "ui")
        await complete(database, agents["reviewer"], {"kind": "approved_review", "summary": "Approved.", "artifactIds": [], "data": {"verdict": "approved", "findings": [], "workspaceRevision": "base"}}, "review")
        await complete(database, agents["tester"], {"kind": "passing_test_run", "summary": "Tests passed.", "artifactIds": [], "data": {"command": "pytest", "exitCode": 0, "testsRun": 1, "workspaceRevision": "base"}}, "test")
        states = {state.rule["id"]: state.status for state in await GateEngine(database).states("gate_session")}
    finally:
        await database.close()

    assert set(states.values()) == {"satisfied"}


@pytest.mark.asyncio
async def test_custom_schema_keywords_are_checked_at_configuration_time(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        unsupported = SessionConfigurationInput(requiredRoleRules=[
            RequiredRoleRule(id="security", role="security", applicability="always", successEvidence="security_approved"),
        ])
        with pytest.raises(ConfigurationError, match="supported JSON-Schema subset"):
            SessionConfigurationService._validate(
                [
                    SessionAgentInput(id="coordinator", role="coordinator"),
                    SessionAgentInput(id="security", role="security", evidenceSchema={"allOf": []}),
                ], "coordinator", unsupported, "snapshot", acknowledged_direct_write=False,
            )
        agents = await gate_session(database, [RequiredRoleRule(
            id="plan", role="planner", applicability="always", successEvidence="accepted_plan", acceptanceFields=["scope"],
        )])
        patch = SessionConfigurationPatch.model_validate({"requiredRoleRules": [{
            "id": "plan", "role": "planner", "applicability": "always", "successEvidence": "accepted_plan",
            "minimumCompletions": 1, "acceptanceFields": ["scope", "risk"],
        }]})
        snapshot, _ = await SessionConfigurationService(database).update("gate_session", 1, patch)
    finally:
        await database.close()

    assert agents["planner"]
    assert snapshot.required_role_rules[0]["acceptanceFields"] == ["scope", "risk"]


@pytest.mark.asyncio
async def test_partial_outcome_requires_explicit_human_acceptance(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await gate_session(database, [])
        result = await CoordinatorCycle(database).execute(
            "gate_session", ScriptedProvider(((StructuredOutput({
                "type": "partial", "finalSummary": "One requested item remains.", "unmetRequirements": ["Run external integration tests."],
            }),),)), ProviderRequest("partial", "fake", ({"role": "user", "content": "Finish."},)),
        )
        async with database.execute("SELECT payload_json FROM events WHERE event_type = 'decision.requested' ORDER BY sequence DESC LIMIT 1") as cursor:
            partial_request = json.loads((await cursor.fetchone())["payload_json"])
        decision_id = partial_request["decisionId"]
        with pytest.raises(CommandRejected):
            await CommandProcessor(database).process("gate_session", parse_session_command({
                "commandId": "wrong-partial", "type": "decision.resolve", "payload": {"decisionId": "wrong", "choice": "deliver_partial"},
            }))
        outcome = await CommandProcessor(database).process("gate_session", parse_session_command({
            "commandId": "accept-partial", "type": "decision.resolve", "payload": {"decisionId": decision_id, "choice": "deliver_partial"},
        }))
    finally:
        await database.close()

    assert result.action is not None and result.action.type == "partial"
    assert partial_request["unmetRequirements"] == ["Run external integration tests."]
    assert outcome.events[-1].payload["status"] == "completed_partial"


@pytest.mark.asyncio
async def test_late_partial_outcome_cannot_override_a_paused_session(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await gate_session(database, [])
        await SessionRepository(database).set_status("gate_session", "paused")
        decision = await CoordinatorCycle(database).request_partial_acceptance("gate_session", PartialAction.model_validate({
            "type": "partial", "finalSummary": "Late partial result.", "unmetRequirements": ["Resume first."],
        }))
        async with database.execute("SELECT status FROM sessions WHERE id = 'gate_session'") as cursor:
            status = (await cursor.fetchone())["status"]
    finally:
        await database.close()

    assert decision is None
    assert status == "paused"
