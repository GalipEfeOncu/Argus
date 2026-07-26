"""Security coverage for the Phase 4.4 approval and grant engine."""

from __future__ import annotations

import pytest

from app.db.database import get_db, transaction
from app.db.repositories import EventRepository, SessionRepository
from app.schemas.session import ApprovalPolicy, SessionAgentInput, SessionConfigurationInput
from app.schemas.session_commands import parse_session_command
from app.services.approval_grant_service import ApprovalGrantService, ApprovalRejected
from app.services.assignment_scheduler import AssignmentScheduler, SchedulerRejected
from app.services.command_processor import CommandProcessor
from app.services.session_configuration_service import SessionConfigurationService


async def configured(
    database, session_id: str = "approval_session", *, profile: str = "balanced", behavior: str = "ask_by_policy",
    preauthorized: list[str] | None = None, acknowledgements: list[str] | None = None,
):
    await SessionRepository(database).create_legacy_session(
        session_id=session_id, name="Approval", project_path="workspace", task="Verify grants", role_configs=[],
    )
    async with transaction(database):
        return await SessionConfigurationService(database).create_initial(
            session_id=session_id,
            agents=[
                SessionAgentInput(id="coordinator", role="coordinator"),
                SessionAgentInput(id="builder", role="builder", capabilities=["workspace.write", "workspace.read", "network.shell"]),
            ],
            coordinator_id="coordinator",
            configuration=SessionConfigurationInput(
                availableAgentIds=["builder"],
                approvalPolicy=ApprovalPolicy(
                    permissionProfile=profile, behavior=behavior, preauthorizedCapabilities=preauthorized or [],
                ),
                acknowledgements=acknowledgements or [],
            ),
            workspace_mode="snapshot", acknowledged_direct_write=False,
        )


async def grant_requested_write(database, session_id: str, *, scope: str = "src", grant_scope: str = "once") -> str:
    service = ApprovalGrantService(database)
    async with transaction(database):
        requested = await service.request_in_transaction(
            session_id, capability="workspace.write", scope_path=scope, scope_summary="Write only the requested session path.",
            operation_class="mutating",
        )
    assert requested.outcome == "ask" and requested.grant_id is not None
    command = parse_session_command({
        "commandId": f"grant_{scope}_{grant_scope}", "type": "approval.resolve",
        "payload": {"approvalId": requested.grant_id, "resolution": "grant", "grantCapabilities": ["workspace.write"],
                    "scopeSummary": "Only the requested session path.", "grantScope": grant_scope},
    })
    event = await EventRepository(database).append(
        event_id=f"resolved_{scope}_{grant_scope}", session_id=session_id, event_type="approval.resolved", actor_id="human",
        payload={"approvalId": requested.grant_id, "resolution": "granted", "grantId": requested.grant_id,
                 "grantScope": grant_scope, "reasonSummary": "Granted."}, timestamp_ms=1,
    )
    async with transaction(database):
        await service.resolve_in_transaction(session_id, command.payload, event.event_id)
    return requested.grant_id


@pytest.mark.asyncio
async def test_grants_are_exact_scoped_expiring_and_bound_to_policy_hash(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        snapshot = await configured(database)
        await grant_requested_write(database, "approval_session", scope="src", grant_scope="once")
        service = ApprovalGrantService(database)
        exact = await service.evaluate("approval_session", capability="workspace.write", scope_path="src", operation_class="mutating")
        broader = await service.evaluate("approval_session", capability="workspace.write", scope_path="src/other", operation_class="mutating")
        async with transaction(database):
            consumed = await service.evaluate(
                "approval_session", capability="workspace.write", scope_path="src", operation_class="mutating", consume_once=True,
            )
        assert consumed.outcome == "allow"
        await grant_requested_write(database, "approval_session", scope="src", grant_scope="session")
        session_exact = await service.evaluate("approval_session", capability="workspace.write", scope_path="src", operation_class="mutating")
        session_widened = await service.evaluate("approval_session", capability="workspace.write", scope_path="other", operation_class="mutating")
        # Updating policy revokes grants immediately; a stale policy hash can
        # never authorize a later tool request.
        processor = CommandProcessor(database)
        await processor.process("approval_session", parse_session_command({
            "commandId": "restrict_write", "type": "session.configuration.update",
            "payload": {"expectedConfigurationVersion": snapshot.version, "patch": {"capabilityOverrides": {"workspace.write": "deny"}}, "confirmConsequences": True},
        }))
        revoked = await service.evaluate("approval_session", capability="workspace.write", scope_path="src", operation_class="mutating")
    finally:
        await database.close()
    assert exact.outcome == "allow"
    assert broader.outcome == "ask"
    assert session_exact.outcome == "allow"
    assert session_widened.outcome == "ask"
    assert revoked.outcome == "deny"


@pytest.mark.asyncio
async def test_once_grant_is_consumed_atomically_at_the_tool_boundary(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await configured(database)
        await grant_requested_write(database, "approval_session", scope="src", grant_scope="once")
        service = ApprovalGrantService(database)
        async with transaction(database):
            first = await service.evaluate(
                "approval_session", capability="workspace.write", scope_path="src", operation_class="mutating", consume_once=True,
            )
            second = await service.evaluate(
                "approval_session", capability="workspace.write", scope_path="src", operation_class="mutating", consume_once=True,
            )
    finally:
        await database.close()
    assert first.outcome == "allow"
    assert second.outcome == "ask"


@pytest.mark.asyncio
async def test_human_cannot_grant_a_broader_capability_or_fake_an_approval(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await configured(database)
        service = ApprovalGrantService(database)
        async with transaction(database):
            requested = await service.request_in_transaction(
                "approval_session", capability="workspace.write", scope_path=".", scope_summary="Workspace only.", operation_class="mutating",
            )
        event = await EventRepository(database).append(
            event_id="bad_grant_event", session_id="approval_session", event_type="approval.resolved", actor_id="human",
            payload={"approvalId": requested.grant_id, "resolution": "granted", "grantId": requested.grant_id,
                     "grantScope": "session", "reasonSummary": "Bad grant."}, timestamp_ms=1,
        )
        widened = parse_session_command({
            "commandId": "widen", "type": "approval.resolve",
            "payload": {"approvalId": requested.grant_id, "resolution": "grant", "grantCapabilities": ["network.shell"],
                        "scopeSummary": "Everything", "grantScope": "session"},
        })
        with pytest.raises(ApprovalRejected, match="only the capability"):
            async with transaction(database):
                await service.resolve_in_transaction("approval_session", widened.payload, event.event_id)
        fake = parse_session_command({
            "commandId": "fake", "type": "approval.resolve",
            "payload": {"approvalId": "not_requested", "resolution": "grant", "grantCapabilities": ["workspace.write"], "scopeSummary": "Nope"},
        })
        with pytest.raises(ApprovalRejected, match="missing, stale"):
            async with transaction(database):
                await service.resolve_in_transaction("approval_session", fake.payload, event.event_id)
    finally:
        await database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["strict", "balanced", "autonomous", "expert_unrestricted"])
async def test_non_bypassable_operations_are_denied_in_every_profile(temporary_sqlite_db, profile: str) -> None:
    database = await get_db()
    try:
        acknowledgements = (["autonomous_permissions"] if profile == "autonomous" else
                            ["expert_unrestricted_permissions"] if profile == "expert_unrestricted" else [])
        await configured(database, profile=profile, acknowledgements=acknowledgements)
        decision = await ApprovalGrantService(database).evaluate(
            "approval_session", capability="outside_workspace", scope_path="../outside", operation_class="mutating",
        )
    finally:
        await database.close()
    assert decision.outcome == "deny"


@pytest.mark.asyncio
async def test_preauthorization_survives_restart_and_deny_interactive_never_prompts(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await configured(
            database, profile="autonomous", behavior="preauthorize_session", preauthorized=["workspace.write"],
            acknowledgements=["autonomous_permissions"],
        )
        await database.close()
        database = await get_db()
        restored = await ApprovalGrantService(database).evaluate(
            "approval_session", capability="workspace.write", scope_path=".", operation_class="mutating",
        )
        await configured(database, "deny_session", profile="balanced", behavior="deny_interactive")
        denied = await ApprovalGrantService(database).evaluate(
            "deny_session", capability="workspace.write", scope_path=".", operation_class="mutating",
        )
    finally:
        await database.close()
    assert restored.outcome == "allow"
    assert denied.outcome == "deny"


@pytest.mark.asyncio
async def test_scheduler_rejects_coordinator_permission_bypass(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        snapshot = await configured(database)
        builder = snapshot.available_agent_ids[0]
        from app.schemas.coordinator_actions import CoordinatorAssignment
        with pytest.raises(SchedulerRejected, match="active policy grant"):
            await AssignmentScheduler(database).accept_coordinator_proposal("approval_session", CoordinatorAssignment(
                proposalId="fake_authority", assigneeAgentId=builder, objective="Write without human grant.",
                acceptanceCriteria=["Never run"], operationClass="mutating", requestedBudget={},
                requestedCapabilities=["workspace.write"], reasonSummary="Coordinator claimed approval.",
            ))
    finally:
        await database.close()
