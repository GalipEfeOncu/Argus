"""Deterministic required-role applicability, evidence, and routing policy."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
import uuid

import aiosqlite

from app.db.repositories import EventRepository, _now_ms, _safe_json
from app.schemas.coordinator_actions import CoordinatorAssignment
from app.services.evidence_schema import matches_json_schema
from app.services.session_configuration_service import ConfigurationSnapshot, SessionConfigurationService


_BUILTIN_EVIDENCE = {
    "planner": "accepted_plan", "builder": "verified_change", "ui_agent": "verified_change",
    "reviewer": "approved_review", "tester": "passing_test_run",
}


@dataclass(frozen=True)
class GateState:
    rule: dict[str, Any]
    status: str
    valid_completions: int


class GateEngine:
    """Keep gate state deterministic and independent from model prose."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._events = EventRepository(db)

    async def states(self, session_id: str) -> tuple[GateState, ...]:
        snapshot = await SessionConfigurationService(self._db).current(session_id)
        applicable = await self._applicable_rule_ids(session_id, snapshot)
        result: list[GateState] = []
        for rule in snapshot.required_role_rules:
            if rule["id"] not in applicable:
                result.append(GateState(rule, "not_applicable", 0))
                continue
            count = await self._valid_completion_count(session_id, rule)
            result.append(GateState(rule, "satisfied" if count >= rule["minimumCompletions"] else "pending", count))
        return tuple(result)

    async def emit_states(self, session_id: str) -> tuple[GateState, ...]:
        """Append the user-visible projection after a deterministic state change."""

        states = await self.states(session_id)
        for state in states:
            evidence = ([{
                "kind": state.rule["successEvidence"], "summary": f"{state.valid_completions} validated completion(s).",
                "artifactIds": [], "data": {},
            }] if state.valid_completions else [])
            payload = {"gateId": state.rule["id"], "role": state.rule["role"], "status": state.status, "evidence": evidence}
            await self._events._append_in_transaction(
                event_id=f"gate_{uuid.uuid4().hex}", session_id=session_id, event_type="gate.status_changed", actor_id="system",
                payload=payload, payload_json=_safe_json(payload), timestamp_ms=_now_ms(), correlation_id=None, command_id=None,
            )
        return states

    async def append_states(self, session_id: str) -> tuple[GateState, ...]:
        """Persist gate state when the caller does not own a database transaction."""

        states = await self.states(session_id)
        for state in states:
            evidence = ([{
                "kind": state.rule["successEvidence"], "summary": f"{state.valid_completions} validated completion(s).",
                "artifactIds": [], "data": {},
            }] if state.valid_completions else [])
            await self._events.append(
                event_id=f"gate_{uuid.uuid4().hex}", session_id=session_id, event_type="gate.status_changed", actor_id="system",
                payload={"gateId": state.rule["id"], "role": state.rule["role"], "status": state.status, "evidence": evidence},
                timestamp_ms=_now_ms(),
            )
        return states

    async def record_evidence(self, session_id: str, assignment: aiosqlite.Row, evidence: list[dict[str, Any]]) -> None:
        """Store every matching evidence attempt, including rejected model prose."""

        async with self._db.execute(
            "SELECT role, snapshot_json FROM session_agents WHERE id = ?", (assignment["assignee_session_agent_id"],)
        ) as cursor:
            agent = await cursor.fetchone()
        if agent is None:
            return
        agent_snapshot = json.loads(agent["snapshot_json"])
        snapshot = await SessionConfigurationService(self._db).current(session_id)
        for rule in snapshot.required_role_rules:
            if rule["role"] != agent["role"]:
                continue
            for item in evidence:
                if item.get("kind") != rule["successEvidence"]:
                    continue
                valid, revision = await self._validate_evidence(
                    session_id, str(agent["role"]), agent_snapshot.get("evidenceSchema"), rule, item,
                )
                await self._db.execute(
                    """INSERT INTO gate_evidence (id, session_id, rule_id, assignment_id, evidence_kind,
                       validation_state, workspace_revision, artifact_ids_json, created_at_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (f"evidence_{uuid.uuid4().hex}", session_id, rule["id"], assignment["id"], item["kind"],
                     "valid" if valid else "invalid", revision, _safe_json(item.get("artifactIds", [])), _now_ms()),
                )
        await self.emit_states(session_id)

    async def invalidate_after_mutation(self, session_id: str, revision: str) -> None:
        """Invalidate only revision-sensitive Reviewer/Tester evidence after a write."""

        cursor = await self._db.execute(
            """UPDATE gate_evidence SET invalidated_at_ms = ?
               WHERE session_id = ? AND validation_state = 'valid' AND invalidated_at_ms IS NULL
                 AND (workspace_revision IS NULL OR workspace_revision != ?)
                 AND assignment_id IN (
                   SELECT assignment.id FROM assignments assignment
                   JOIN session_agents agent ON agent.id = assignment.assignee_session_agent_id
                   WHERE agent.role IN ('reviewer', 'tester')
                 )""",
            (_now_ms(), session_id, revision),
        )
        if cursor.rowcount:
            await self.emit_states(session_id)

    async def route_unsatisfied(self, session_id: str) -> tuple[str, ...]:
        """Queue eligible read-only gate work before a final result is permitted."""

        from app.services.assignment_scheduler import AssignmentScheduler

        snapshot = await SessionConfigurationService(self._db).current(session_id)
        queued: list[str] = []
        for state in await self.states(session_id):
            if state.status != "pending":
                continue
            needed = max(0, state.rule["minimumCompletions"] - state.valid_completions - await self._active_gate_assignment_count(session_id, state.rule))
            candidates = [agent for agent in snapshot.agent_snapshots if agent["id"] in snapshot.available_agent_ids and agent["role"] == state.rule["role"]]
            for index in range(needed):
                agent = candidates[index % len(candidates)]
                proposal = CoordinatorAssignment.model_validate({
                    "proposalId": f"gate_{state.rule['id']}_{uuid.uuid4().hex}", "assigneeAgentId": agent["id"],
                    "objective": f"Produce validated {state.rule['role']} gate evidence.",
                    "acceptanceCriteria": [f"Return structured {state.rule['successEvidence']} evidence.", "Use the current workspace revision when applicable."],
                    "operationClass": "read_only", "requestedBudget": {}, "requestedCapabilities": [],
                    "reasonSummary": f"Required gate '{state.rule['id']}' is still pending.",
                })
                queued.append(await AssignmentScheduler(self._db).accept_coordinator_proposal(session_id, proposal))
        return tuple(queued)

    async def _validate_evidence(
        self, session_id: str, role: str, custom_schema: object, rule: dict[str, Any], item: dict[str, Any],
    ) -> tuple[bool, str | None]:
        data = item.get("data")
        if not isinstance(data, dict):
            return False, None
        revision = await self._workspace_revision(session_id)
        expected = _BUILTIN_EVIDENCE.get(role)
        if expected is None:
            return (isinstance(custom_schema, dict) and matches_json_schema(data, custom_schema), _string_or_none(data.get("workspaceRevision")))
        if item.get("kind") != expected:
            return False, None
        if role == "planner":
            plan = data.get("plan")
            fields = rule.get("acceptanceFields", [])
            valid = isinstance(plan, dict) and isinstance(plan.get("steps"), list) and bool(plan["steps"])
            valid = valid and all(isinstance(step, str) and step.strip() for step in plan["steps"])
            valid = valid and all(_nonempty(plan.get(field)) for field in fields) if isinstance(plan, dict) else False
            return valid, None
        if role in {"builder", "ui_agent"}:
            if data.get("changeKind") == "diff" and item.get("artifactIds") and _revision_matches(data, revision):
                return True, revision
            return data.get("changeKind") == "verified_no_change" and _nonempty(data.get("verification")), revision
        if role == "reviewer":
            return data.get("verdict") == "approved" and isinstance(data.get("findings"), list) and _revision_matches(data, revision), revision
        if role == "tester":
            return (
                isinstance(data.get("command"), str) and bool(data["command"].strip()) and data.get("exitCode") == 0
                and isinstance(data.get("testsRun"), int) and data["testsRun"] >= 1 and _revision_matches(data, revision), revision
            )
        return False, None

    async def _applicable_rule_ids(self, session_id: str, snapshot: ConfigurationSnapshot) -> set[str]:
        async with self._db.execute("SELECT 1 FROM artifacts WHERE session_id = ? AND kind = 'diff' LIMIT 1", (session_id,)) as cursor:
            has_changes = await cursor.fetchone() is not None
        used: set[str] = set()
        async with self._db.execute(
            "SELECT proposal_json FROM assignment_proposals WHERE session_id = ? AND validation_state = 'accepted'", (session_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            used.update(str(value) for value in json.loads(row["proposal_json"]).get("requestedCapabilities", []))
        return {rule["id"] for rule in snapshot.required_role_rules if rule["applicability"] == "always" or (rule["applicability"] == "when_changes" and has_changes) or (rule["applicability"] == "when_capability_used" and rule["capability"] in used)}

    async def _valid_completion_count(self, session_id: str, rule: dict[str, Any]) -> int:
        async with self._db.execute(
            """SELECT COUNT(DISTINCT evidence.assignment_id) AS total FROM gate_evidence evidence
               JOIN assignments assignment ON assignment.id = evidence.assignment_id
               JOIN session_agents agent ON agent.id = assignment.assignee_session_agent_id
               WHERE evidence.session_id = ? AND evidence.rule_id = ? AND evidence.evidence_kind = ?
                 AND evidence.validation_state = 'valid' AND evidence.invalidated_at_ms IS NULL AND agent.role = ?""",
            (session_id, rule["id"], rule["successEvidence"], rule["role"]),
        ) as cursor:
            return int((await cursor.fetchone())["total"])

    async def _active_gate_assignment_count(self, session_id: str, rule: dict[str, Any]) -> int:
        marker = f"Return structured {rule['successEvidence']} evidence."
        async with self._db.execute(
            """SELECT COUNT(*) AS total FROM assignments assignment JOIN session_agents agent ON agent.id = assignment.assignee_session_agent_id
               WHERE assignment.session_id = ? AND assignment.state IN ('created', 'running') AND agent.role = ?
                 AND json_extract(assignment.acceptance_criteria_json, '$[0]') = ?""",
            (session_id, rule["role"], marker),
        ) as cursor:
            return int((await cursor.fetchone())["total"])

    async def _workspace_revision(self, session_id: str) -> str | None:
        async with self._db.execute("SELECT revision_checksum FROM workspaces WHERE session_id = ?", (session_id,)) as cursor:
            row = await cursor.fetchone()
        return None if row is None else str(row["revision_checksum"])


def _revision_matches(data: dict[str, Any], revision: str | None) -> bool:
    return revision is not None and data.get("workspaceRevision") == revision


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _nonempty(value: object) -> bool:
    return bool(value) and (not isinstance(value, str) or bool(value.strip()))
