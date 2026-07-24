import json

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.database import get_db, transaction
from app.db.repositories import EventRepository, SessionRepository
from app.main import app
from app.schemas.session import ApprovalPolicy, RequiredRoleRule, SessionAgentInput, SessionConfigurationInput
from app.schemas.session_commands import parse_session_command
from app.services.command_processor import CommandProcessor, CommandRejected
from app.services.session_configuration_service import ConfigurationError, SessionConfigurationService


async def configured_session(
    database: aiosqlite.Connection, session_id: str = "session_config", *, acknowledgements: list[str] | None = None,
    available_agent_ids: list[str] | None = None,
) -> object:
    await SessionRepository(database).create_legacy_session(
        session_id=session_id, name="Configured", project_path="workspace", task="Verify configuration", role_configs=[],
    )
    agents = [
        SessionAgentInput(id="coordinator", role="coordinator"),
        SessionAgentInput(id="builder", role="builder"),
        SessionAgentInput(id="reviewer", role="reviewer"),
    ]
    async with transaction(database):
        snapshot = await SessionConfigurationService(database).create_initial(
            session_id=session_id, agents=agents, coordinator_id="coordinator",
            configuration=SessionConfigurationInput(
                availableAgentIds=available_agent_ids or ["builder", "reviewer"], acknowledgements=acknowledgements or [],
            ),
            workspace_mode="snapshot", acknowledged_direct_write=False,
        )
    return snapshot


@pytest.mark.asyncio
async def test_configuration_validation_defaults_and_immutable_agent_snapshots(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        initial = await configured_session(database)
        snapshot = await SessionConfigurationService(database).current("session_config")
        async with database.execute("SELECT snapshot_json FROM session_agents WHERE session_id = ?", ("session_config",)) as cursor:
            rows = await cursor.fetchall()
        with pytest.raises(aiosqlite.IntegrityError, match="session agents are immutable"):
            await database.execute("UPDATE session_agents SET role = 'tester' WHERE session_id = 'session_config' AND role = 'builder'")
    finally:
        await database.close()

    assert snapshot.version == 1
    assert snapshot.execution_limits["maxAssignmentAttempts"] == 8
    assert snapshot.approval_policy["permissionProfile"] == "balanced"
    assert len(snapshot.policy_hash) == 64
    assert {json.loads(row["snapshot_json"])["id"] for row in rows} == {"coordinator", "builder", "reviewer"}


def test_configuration_rejects_capabilityless_gates_and_unsafe_preauthorization() -> None:
    agents = [
        SessionAgentInput(id="coordinator", role="coordinator"),
        SessionAgentInput(id="reviewer", role="reviewer", capabilities=["workspace.read"]),
    ]
    with pytest.raises(ConfigurationError, match="required-role agent"):
        SessionConfigurationService._validate(
            agents, "coordinator", SessionConfigurationInput(
                availableAgentIds=["reviewer"], requiredRoleRules=[RequiredRoleRule(
                    id="cap_gate", role="reviewer", applicability="when_capability_used", capability="test.run",
                    successEvidence="approved_review",
                )],
            ), "snapshot", acknowledged_direct_write=False,
        )
    with pytest.raises(ConfigurationError, match="Autonomous"):
        SessionConfigurationService._validate(
            agents, "coordinator", SessionConfigurationInput(
                availableAgentIds=["reviewer"], approvalPolicy=ApprovalPolicy(
                    permissionProfile="balanced", behavior="preauthorize_session", preauthorizedCapabilities=["workspace.write"],
                ),
            ), "snapshot", acknowledged_direct_write=False,
        )


@pytest.mark.asyncio
async def test_configuration_update_previews_consequences_then_interrupts_invalid_active_work(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        initial = await configured_session(database)
        builder_id, reviewer_id = initial.available_agent_ids
        event = await EventRepository(database).append(
            event_id="assignment_created", session_id="session_config", event_type="message.created", actor_id="system",
            payload={"messageId": "m1", "authorId": "system", "authorKind": "system", "content": "created"}, timestamp_ms=1,
        )
        await database.execute(
            """INSERT INTO assignments (id, session_id, parent_id, assignee_session_agent_id, state, operation_class,
               acceptance_criteria_json, budget_json, configuration_version, writer_lease_id, created_event_id,
               terminal_event_id, created_at_ms, updated_at_ms)
               VALUES ('active_builder', 'session_config', NULL, ?, 'running', 'mutating', '[]', '{}', 1, NULL, ?, NULL, 1, 1)""",
            (builder_id, event.event_id),
        )
        await database.commit()
        processor = CommandProcessor(database)
        preview = await processor.process("session_config", parse_session_command({
            "commandId": "remove_builder_preview", "type": "session.configuration.update",
            "payload": {"expectedConfigurationVersion": 1, "patch": {"availableAgentIds": [reviewer_id]}},
        }))
        confirmed = await processor.process("session_config", parse_session_command({
            "commandId": "remove_builder_confirm", "type": "session.configuration.update",
            "payload": {
                "expectedConfigurationVersion": 1, "patch": {"availableAgentIds": [reviewer_id]},
                "confirmConsequences": True,
            },
        }))
        snapshot = await SessionConfigurationService(database).current("session_config")
        async with database.execute("SELECT state FROM assignments WHERE id = 'active_builder'") as cursor:
            state = (await cursor.fetchone())["state"]
    finally:
        await database.close()

    assert preview.events[0].event_type == "error.created"
    assert preview.events[0].payload["code"] == "configuration_preview_required"
    assert [event.event_type for event in confirmed.events] == ["session.configuration_updated", "assignment.cancelled"]
    assert snapshot.version == 2 and snapshot.available_agent_ids == [reviewer_id]
    assert state == "interrupted"


@pytest.mark.asyncio
async def test_agent_addition_and_permission_increase_then_confirmed_decrease(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        initial = await configured_session(
            database, acknowledgements=["autonomous_permissions"], available_agent_ids=["builder"],
        )
        builder_id = initial.available_agent_ids[0]
        async with database.execute("SELECT id FROM session_agents WHERE session_id = ? AND role = 'reviewer'", ("session_config",)) as cursor:
            reviewer_id = (await cursor.fetchone())["id"]
        processor = CommandProcessor(database)
        added = await processor.process("session_config", parse_session_command({
            "commandId": "add_agent", "type": "session.configuration.update",
            "payload": {"expectedConfigurationVersion": 1, "patch": {"availableAgentIds": [builder_id, reviewer_id]}},
        }))
        increased = await processor.process("session_config", parse_session_command({
            "commandId": "increase_permission", "type": "session.configuration.update",
            "payload": {"expectedConfigurationVersion": 2, "patch": {"permissionProfile": "autonomous"}},
        }))
        preview = await processor.process("session_config", parse_session_command({
            "commandId": "decrease_permission_preview", "type": "session.configuration.update",
            "payload": {"expectedConfigurationVersion": 3, "patch": {"permissionProfile": "balanced"}},
        }))
        decreased = await processor.process("session_config", parse_session_command({
            "commandId": "decrease_permission_confirm", "type": "session.configuration.update",
            "payload": {
                "expectedConfigurationVersion": 3, "patch": {"permissionProfile": "balanced"},
                "confirmConsequences": True,
            },
        }))
        snapshot = await SessionConfigurationService(database).current("session_config")
    finally:
        await database.close()

    assert added.events[0].payload["configurationVersion"] == 2
    assert increased.events[0].payload["configurationVersion"] == 3
    assert preview.events[0].payload["code"] == "configuration_preview_required"
    assert decreased.events[0].payload["configurationVersion"] == 4
    assert snapshot.approval_policy["permissionProfile"] == "balanced"


@pytest.mark.asyncio
async def test_updates_are_idempotent_reject_stale_versions_and_preserve_consumed_counters(temporary_sqlite_db) -> None:
    database = await get_db()
    try:
        await configured_session(database)
        await database.execute(
            """INSERT INTO limit_counters (id, session_id, scope_type, scope_id, counter_kind, consumed_value,
               threshold_value, warning_emitted, last_event_id, updated_at_ms)
               VALUES ('tokens', 'session_config', 'session', 'session_config', 'tokens', 120, 500000, 0, NULL, 1)"""
        )
        await database.commit()
        processor = CommandProcessor(database)
        command = parse_session_command({
            "commandId": "lower_token_limit", "type": "session.configuration.update",
            "payload": {"expectedConfigurationVersion": 1, "patch": {"executionLimits": {"maxSessionTokens": 100}}},
        })
        first = await processor.process("session_config", command)
        duplicate = await processor.process("session_config", command)
        confirmed = await processor.process("session_config", parse_session_command({
            "commandId": "lower_token_limit_confirm", "type": "session.configuration.update",
            "payload": {
                "expectedConfigurationVersion": 1, "patch": {"executionLimits": {"maxSessionTokens": 100}},
                "confirmConsequences": True,
            },
        }))
        with pytest.raises(CommandRejected, match="stale_configuration_version"):
            await processor.process("session_config", parse_session_command({
                "commandId": "stale", "type": "session.configuration.update",
                "payload": {"expectedConfigurationVersion": 1, "patch": {"limitResolution": "stop"}},
            }))
        async with database.execute("SELECT consumed_value FROM limit_counters WHERE id = 'tokens'") as cursor:
            consumed = (await cursor.fetchone())["consumed_value"]
        snapshot = await SessionConfigurationService(database).current("session_config")
    finally:
        await database.close()

    assert first.duplicate is False and duplicate.duplicate is True and duplicate.events == first.events
    assert first.events[0].payload["code"] == "configuration_preview_required"
    assert confirmed.events[0].event_type == "session.configuration_updated"
    assert snapshot.execution_limits["maxSessionTokens"] == 100
    assert consumed == 120


def test_post_sessions_returns_normalized_defaults_validation_codes_and_restart_persistence(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "configuration-rest.db"
    monkeypatch.setattr(settings, "db_path", str(database_path))
    project = tmp_path / "project"
    project.mkdir()
    payload = {
        "projectPath": str(project), "goal": "Add coverage", "coordinatorAgentId": "coord",
        "agents": [
            {"id": "coord", "role": "coordinator"},
            {"id": "builder", "role": "builder"},
            {"id": "reviewer", "role": "reviewer"},
        ],
        "configuration": {
            "availableAgentIds": ["builder", "reviewer"],
            "requiredRoleRules": [{
                "id": "review_gate", "role": "reviewer", "applicability": "when_changes",
                "successEvidence": "approved_review", "minimumCompletions": 1,
            }],
        },
    }
    with TestClient(app) as client:
        created = client.post("/sessions/", json=payload)
        second = client.post("/sessions/", json=payload)
        invalid = client.post("/sessions/", json={
            **payload, "agents": payload["agents"] + [{"id": "builder", "role": "tester"}],
        })
    # A new application lifespan simulates sidecar restart and must still read
    # the immutable normalized snapshot from SQLite.
    with TestClient(app) as restarted:
        persisted = restarted.get(f"/sessions/{created.json()['id']}/configuration")

    assert created.status_code == 200
    assert second.status_code == 200
    assert created.json()["availableAgentIds"] != second.json()["availableAgentIds"]
    assert {item["sourceAgentId"] for item in created.json()["agentSnapshots"]} == {"coord", "builder", "reviewer"}
    assert created.json()["configurationVersion"] == 1
    assert created.json()["executionLimits"]["maxWallClockSeconds"] == 14_400
    assert persisted.status_code == 200 and persisted.json()["policyHash"] == created.json()["policyHash"]
    assert invalid.status_code == 422 and invalid.json()["detail"]["code"] == "duplicate_agent_id"
