"""Deterministic, durable session-configuration policy service.

This module owns defaults, domain validation, immutable snapshots, and the
consequence decision used by the canonical command processor.  It deliberately
does not delegate any of those decisions to an agent loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import uuid
from typing import Any

import aiosqlite
from pydantic import ValidationError

from app.db.repositories import _now_ms, _safe_json
from app.schemas.session import SessionAgentInput, SessionConfigurationInput
from app.schemas.session_commands import SessionConfigurationPatch


class ConfigurationError(ValueError):
    """Stable validation error returned to REST and command callers."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ConfigurationSnapshot:
    id: str
    session_id: str
    version: int
    available_agent_ids: list[str]
    required_role_rules: list[dict[str, Any]]
    execution_limits: dict[str, Any]
    approval_policy: dict[str, Any]
    workspace_policy: dict[str, Any]
    acknowledgements: list[str]
    policy_hash: str
    agent_snapshots: list[dict[str, Any]]

    def wire_value(self) -> dict[str, Any]:
        return {
            "configurationVersion": self.version,
            "availableAgentIds": self.available_agent_ids,
            "requiredRoleRules": self.required_role_rules,
            "executionLimits": self.execution_limits,
            "approvalPolicy": self.approval_policy,
            "workspacePolicy": self.workspace_policy,
            "acknowledgements": self.acknowledgements,
            "policyHash": self.policy_hash,
            "agentSnapshots": self.agent_snapshots,
        }


@dataclass(frozen=True)
class ConfigurationConsequences:
    requires_confirmation: bool
    summary: str
    invalid_assignment_ids: tuple[str, ...]


_KNOWN_CAPABILITIES = frozenset({"workspace.read", "workspace.write", "test.run", "search.files"})
_EVIDENCE_BY_ROLE = {
    "planner": "accepted_plan",
    "builder": "verified_change",
    "ui_agent": "verified_change",
    "reviewer": "approved_review",
    "tester": "passing_test_run",
}
_PROFILE_RANK = {"strict": 0, "balanced": 1, "autonomous": 2, "expert_unrestricted": 3}
_BEHAVIOR_RANK = {"deny_interactive": 0, "ask_each_time": 1, "ask_by_policy": 2, "preauthorize_session": 3}
_COUNTER_LIMIT_FIELDS = {
    "revisions": "maxRevisionsPerFinding", "assignment_attempts": "maxAssignmentAttempts",
    "model_iterations": "maxModelIterationsPerAssignment", "tool_calls": "maxToolCallsPerAssignment",
    "tokens": "maxSessionTokens", "wall_clock_seconds": "maxWallClockSeconds",
    "parallel_read_only_assignments": "maxParallelReadOnlyAssignments",
}


def _canonical_policy_hash(value: dict[str, Any]) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _model_dump(value: Any) -> dict[str, Any]:
    return value.model_dump(by_alias=True, mode="json")


class SessionConfigurationService:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    @staticmethod
    def legacy_agents(role_configs: list[dict[str, Any]]) -> list[SessionAgentInput]:
        """Turn transitional role configs into immutable, non-secret snapshots."""

        result: list[SessionAgentInput] = []
        for index, config in enumerate(role_configs):
            if not config.get("enabled", True):
                continue
            role = str(config["role"])
            result.append(SessionAgentInput(
                id=f"legacy_{index}_{role}", role=role, capabilities=[],
                model_snapshot={key: config[key] for key in ("providerId", "modelId") if config.get(key) is not None},
            ))
        return result

    @staticmethod
    def _required_acknowledgements(configuration: SessionConfigurationInput, workspace_mode: str) -> set[str]:
        needed: set[str] = set()
        if workspace_mode == "direct_write":
            needed.add("direct_write_limited_rollback")
        profile = configuration.approval_policy.permission_profile
        if profile == "autonomous":
            needed.add("autonomous_permissions")
        elif profile == "expert_unrestricted":
            needed.add("expert_unrestricted_permissions")
        return needed

    @staticmethod
    def _validate(
        agents: list[SessionAgentInput], coordinator_id: str, configuration: SessionConfigurationInput,
        workspace_mode: str, *, acknowledged_direct_write: bool,
    ) -> list[str]:
        agent_ids = [agent.id for agent in agents]
        if len(set(agent_ids)) != len(agent_ids):
            raise ConfigurationError("duplicate_agent_id", "Each session agent id must be unique.")
        if coordinator_id in {agent.id for agent in agents if agent.role != "coordinator"}:
            raise ConfigurationError("invalid_coordinator", "The coordinator must be a coordinator agent.")
        available = configuration.available_agent_ids
        if available is None:
            available = [agent.id for agent in agents if agent.id != coordinator_id and agent.role != "coordinator"]
        if len(set(available)) != len(available):
            raise ConfigurationError("duplicate_available_agent_id", "Available agent ids must be unique.")
        if coordinator_id in available:
            raise ConfigurationError("coordinator_in_available_pool", "The coordinator cannot be in availableAgentIds.")
        by_id = {agent.id: agent for agent in agents}
        unknown = set(available) - by_id.keys()
        if unknown:
            raise ConfigurationError("unknown_available_agent", "Available agents must be immutable session-agent snapshots.")
        for rule in configuration.required_role_rules:
            eligible = [by_id[agent_id] for agent_id in available if by_id[agent_id].role == rule.role]
            if not eligible:
                raise ConfigurationError("required_role_unavailable", f"Required role '{rule.role}' has no eligible available agent.")
            expected_evidence = _EVIDENCE_BY_ROLE.get(rule.role)
            if expected_evidence is not None and rule.success_evidence != expected_evidence:
                raise ConfigurationError("unsupported_evidence", f"Role '{rule.role}' requires '{expected_evidence}' evidence.")
            if rule.applicability == "when_capability_used" and not any(rule.capability in agent.capabilities for agent in eligible):
                raise ConfigurationError("required_role_capability_unavailable", "An eligible required-role agent must have the configured capability.")
        limits = configuration.execution_limits
        if configuration.required_role_rules and any(
            value == 0 for value in (
                limits.max_assignment_attempts, limits.max_model_iterations_per_assignment,
                limits.max_session_tokens, limits.max_wall_clock_seconds,
            )
        ):
            raise ConfigurationError("required_role_limit_conflict", "Required role gates cannot use a zero execution limit.")
        policy = configuration.approval_policy
        if not set(policy.preauthorized_capabilities) <= _KNOWN_CAPABILITIES:
            raise ConfigurationError("unsafe_preauthorization", "Only workspace-scoped safe capabilities may be pre-authorized.")
        if policy.behavior != "preauthorize_session" and policy.preauthorized_capabilities:
            raise ConfigurationError("preauthorization_behavior_mismatch", "Pre-authorized capabilities require preauthorize_session behavior.")
        if policy.behavior == "preauthorize_session" and policy.permission_profile != "autonomous":
            raise ConfigurationError("unsafe_preauthorization", "Session pre-authorization requires the Autonomous permission profile.")
        if workspace_mode == "direct_write" and "workspace.write" in policy.preauthorized_capabilities:
            raise ConfigurationError("unsafe_preauthorization", "Direct-write workspace access cannot be pre-authorized.")
        if workspace_mode == "direct_write" and not acknowledged_direct_write:
            raise ConfigurationError("direct_write_acknowledgement_required", "Direct-write mode requires explicit limited-rollback acknowledgement.")
        acknowledgements = set(configuration.acknowledgements)
        missing = SessionConfigurationService._required_acknowledgements(configuration, workspace_mode) - acknowledgements
        # The compatibility boolean is retained as an acknowledgement descriptor.
        if workspace_mode == "direct_write" and acknowledged_direct_write:
            missing.discard("direct_write_limited_rollback")
        if missing:
            raise ConfigurationError("acknowledgement_required", "Required acknowledgement is missing.")
        return available

    async def create_initial(
        self, *, session_id: str, agents: list[SessionAgentInput], coordinator_id: str,
        configuration: SessionConfigurationInput, workspace_mode: str, acknowledged_direct_write: bool,
    ) -> ConfigurationSnapshot:
        available = self._validate(agents, coordinator_id, configuration, workspace_mode, acknowledged_direct_write=acknowledged_direct_write)
        now = _now_ms()
        namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"argus-session:{session_id}")
        snapshot_ids = {agent.id: str(uuid.uuid5(namespace, agent.id)) for agent in agents}
        agent_snapshots = [
            {"id": snapshot_ids[agent.id], "sourceAgentId": agent.id, "role": agent.role, "capabilities": agent.capabilities}
            for agent in agents
        ]
        for agent in agents:
            snapshot = _model_dump(agent)
            await self._db.execute(
                """INSERT INTO session_agents (id, session_id, agent_definition_id, role, snapshot_json, model_snapshot_json, skill_snapshot_json, created_at_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (snapshot_ids[agent.id], session_id, agent.agent_definition_id, agent.role, _safe_json(snapshot),
                 _safe_json(agent.model_snapshot), _safe_json(agent.skill_snapshot), now),
            )
        return await self._insert_snapshot(
            session_id=session_id, version=1, available_agent_ids=[snapshot_ids[agent_id] for agent_id in available],
            required_role_rules=[_model_dump(rule) for rule in configuration.required_role_rules],
            execution_limits=_model_dump(configuration.execution_limits),
            approval_policy=_model_dump(configuration.approval_policy),
            workspace_policy={"mode": workspace_mode},
            acknowledgements=sorted(set(configuration.acknowledgements) | (
                {"direct_write_limited_rollback"} if workspace_mode == "direct_write" and acknowledged_direct_write else set()
            )), agent_snapshots=agent_snapshots,
        )

    async def current(self, session_id: str) -> ConfigurationSnapshot:
        async with self._db.execute(
            "SELECT * FROM session_configurations WHERE session_id = ? ORDER BY version DESC LIMIT 1", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise ConfigurationError("configuration_not_found", "Session configuration was not found.")
        approval = json.loads(row["approval_behavior_json"])
        agent_snapshots = []
        async with self._db.execute("SELECT id, role, snapshot_json FROM session_agents WHERE session_id = ? ORDER BY created_at_ms, id", (session_id,)) as cursor:
            agent_rows = await cursor.fetchall()
        for agent in agent_rows:
            raw = json.loads(agent["snapshot_json"])
            agent_snapshots.append({
                "id": agent["id"], "sourceAgentId": raw["id"], "role": agent["role"],
                "capabilities": raw.get("capabilities", []),
            })
        return ConfigurationSnapshot(
            row["id"], row["session_id"], row["version"], json.loads(row["available_agent_ids_json"]),
            json.loads(row["required_role_rules_json"]), json.loads(row["execution_limits_json"]),
            approval["approvalPolicy"], approval["workspacePolicy"], json.loads(row["acknowledgements_json"]), row["policy_hash"], agent_snapshots,
        )

    async def _insert_snapshot(
        self, *, session_id: str, version: int, available_agent_ids: list[str], required_role_rules: list[dict[str, Any]],
        execution_limits: dict[str, Any], approval_policy: dict[str, Any], workspace_policy: dict[str, Any], acknowledgements: list[str],
        agent_snapshots: list[dict[str, Any]] | None = None,
    ) -> ConfigurationSnapshot:
        policy_value = {
            "availableAgentIds": available_agent_ids, "requiredRoleRules": required_role_rules,
            "executionLimits": execution_limits, "approvalPolicy": approval_policy, "workspacePolicy": workspace_policy,
        }
        policy_hash = _canonical_policy_hash(policy_value)
        snapshot = ConfigurationSnapshot(str(uuid.uuid4()), session_id, version, available_agent_ids, required_role_rules,
                                         execution_limits, approval_policy, workspace_policy, acknowledgements, policy_hash,
                                         agent_snapshots if agent_snapshots is not None else (await self.current(session_id)).agent_snapshots)
        await self._db.execute(
            """INSERT INTO session_configurations (id, session_id, version, available_agent_ids_json, required_role_rules_json,
               execution_limits_json, approval_behavior_json, acknowledgements_json, policy_hash, created_at_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (snapshot.id, session_id, version, _safe_json(available_agent_ids), _safe_json(required_role_rules),
             _safe_json(execution_limits), _safe_json({"approvalPolicy": approval_policy, "workspacePolicy": workspace_policy}),
             _safe_json(acknowledgements), policy_hash, _now_ms()),
        )
        await self._db.execute(
            "UPDATE sessions SET policy_snapshot_json = ?, updated_at_ms = ? WHERE id = ?",
            (_safe_json(snapshot.wire_value()), _now_ms(), session_id),
        )
        return snapshot

    async def consequences(self, session_id: str, current: ConfigurationSnapshot, patch: SessionConfigurationPatch) -> ConfigurationConsequences:
        candidate = self._apply_patch(current, patch)
        removed = set(current.available_agent_ids) - set(candidate["availableAgentIds"])
        old_profile = current.approval_policy["permissionProfile"]
        next_policy = candidate["approvalPolicy"]
        reduced_permission = (
            _PROFILE_RANK[next_policy["permissionProfile"]] < _PROFILE_RANK[old_profile]
            or _BEHAVIOR_RANK[next_policy["behavior"]] < _BEHAVIOR_RANK[current.approval_policy["behavior"]]
            or not set(next_policy["preauthorizedCapabilities"]).issuperset(current.approval_policy["preauthorizedCapabilities"])
        )
        async with self._db.execute(
            """SELECT id, assignee_session_agent_id FROM assignments
               WHERE session_id = ? AND state IN ('created', 'pending', 'running', 'working')""", (session_id,)
        ) as cursor:
            active = await cursor.fetchall()
        invalid = tuple(row["id"] for row in active if row["assignee_session_agent_id"] in removed or reduced_permission)
        async with self._db.execute(
            "SELECT counter_kind, consumed_value FROM limit_counters WHERE session_id = ?", (session_id,)
        ) as cursor:
            counters = await cursor.fetchall()
        limit_exceeded = any(
            (field := _COUNTER_LIMIT_FIELDS.get(row["counter_kind"])) is not None
            and candidate["executionLimits"].get(field) is not None
            and row["consumed_value"] > candidate["executionLimits"][field]
            for row in counters
        )
        if limit_exceeded:
            invalid = tuple(dict.fromkeys((*invalid, *(row["id"] for row in active))))
        parts: list[str] = []
        if invalid:
            parts.append(f"interrupt {len(invalid)} active assignment(s)")
        if removed:
            parts.append("remove agents from future dispatch")
        if reduced_permission:
            parts.append("reduce permission for future work")
        if limit_exceeded:
            parts.append("apply a reduced limit already below consumed usage")
        return ConfigurationConsequences(bool(parts), "; ".join(parts) or "No active-work consequences.", invalid)

    def _apply_patch(self, current: ConfigurationSnapshot, patch: SessionConfigurationPatch) -> dict[str, Any]:
        candidate = current.wire_value()
        fields = patch.model_fields_set
        if "available_agent_ids" in fields:
            candidate["availableAgentIds"] = patch.available_agent_ids
        if "required_role_rules" in fields:
            candidate["requiredRoleRules"] = [_model_dump(rule) for rule in patch.required_role_rules or []]
        if "execution_limits" in fields:
            candidate["executionLimits"] = {
                **candidate["executionLimits"],
                **patch.execution_limits.model_dump(by_alias=True, mode="json", exclude_unset=True),
            }
        policy = dict(candidate["approvalPolicy"])
        if "approval_behavior" in fields:
            policy["behavior"] = patch.approval_behavior
        if "permission_profile" in fields:
            policy["permissionProfile"] = patch.permission_profile
        if "preauthorized_capabilities" in fields:
            policy["preauthorizedCapabilities"] = patch.preauthorized_capabilities
        if "limit_resolution" in fields:
            policy["limitResolution"] = patch.limit_resolution
        candidate["approvalPolicy"] = policy
        return candidate

    async def update(self, session_id: str, expected_version: int, patch: SessionConfigurationPatch) -> tuple[ConfigurationSnapshot, ConfigurationConsequences]:
        current = await self.current(session_id)
        if current.version != expected_version:
            raise ConfigurationError("stale_configuration_version", "Configuration version is stale; refresh and retry.")
        candidate = self._apply_patch(current, patch)
        async with self._db.execute("SELECT id, role, snapshot_json FROM session_agents WHERE session_id = ?", (session_id,)) as cursor:
            rows = await cursor.fetchall()
        agents = [SessionAgentInput.model_validate({
            **json.loads(row["snapshot_json"]), "id": row["id"], "role": row["role"],
        }) for row in rows]
        coordinator = next((agent.id for agent in agents if agent.role == "coordinator"), "coordinator")
        try:
            configuration = SessionConfigurationInput(
                availableAgentIds=candidate["availableAgentIds"], requiredRoleRules=candidate["requiredRoleRules"],
                executionLimits=candidate["executionLimits"], approvalPolicy=candidate["approvalPolicy"],
                workspacePolicy=candidate["workspacePolicy"], acknowledgements=current.acknowledgements,
            )
        except ValidationError as error:
            raise ConfigurationError("invalid_configuration_patch", "The configuration patch is not a valid normalized configuration.") from error
        self._validate(agents, coordinator, configuration, str(candidate["workspacePolicy"]["mode"]), acknowledged_direct_write=True)
        consequences = await self.consequences(session_id, current, patch)
        snapshot = await self._insert_snapshot(
            session_id=session_id, version=current.version + 1, available_agent_ids=candidate["availableAgentIds"],
            required_role_rules=candidate["requiredRoleRules"], execution_limits=candidate["executionLimits"],
            approval_policy=candidate["approvalPolicy"], workspace_policy=candidate["workspacePolicy"],
            acknowledgements=current.acknowledgements,
            agent_snapshots=current.agent_snapshots,
        )
        return snapshot, consequences
