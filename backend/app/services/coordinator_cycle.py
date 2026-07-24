"""Deterministic validation around one structured Coordinator decision."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import json
from typing import Any, ClassVar

import aiosqlite
from pydantic import ValidationError

from app.providers.protocol import (
    Cancelled,
    Finished,
    Provider,
    ProviderRequest,
    RetryableError,
    StructuredOutput,
    TerminalError,
)
from app.schemas.coordinator_actions import (
    AssignmentsAction,
    CoordinatorAction,
    FinalAction,
    parse_coordinator_action,
)
from app.services.session_configuration_service import ConfigurationSnapshot, SessionConfigurationService


class CoordinatorActionRejected(ValueError):
    """A syntactically valid model action that violates runtime policy."""

    def __init__(self, code: str, summary: str) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary


@dataclass(frozen=True)
class CoordinatorCycleResult:
    action: CoordinatorAction | None
    correction_requested: bool
    stopped: bool
    resolution: str | None
    error_code: str | None = None
    error_summary: str | None = None

    @property
    def visible_summary(self) -> str | None:
        if self.action is None:
            return self.error_summary
        if isinstance(self.action, AssignmentsAction):
            return self.action.routing_summary
        return getattr(self.action, "final_summary", getattr(self.action, "routing_summary", None))


class CoordinatorCycle:
    """Runs one action-only Coordinator turn without granting it control-plane power.

    This service deliberately stops at validated proposals.  Assignment creation,
    permissions, leases, counters, dispatch, and gate writes remain scheduler
    responsibilities in the following runtime slice.
    """

    _active_streams: ClassVar[dict[str, tuple[Provider, str]]] = {}
    _superseded_sessions: ClassVar[set[str]] = set()

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    def supersede(self, session_id: str) -> None:
        """Let a new human instruction end a currently streaming decision promptly."""

        self._superseded_sessions.add(session_id)

    @classmethod
    async def supersede_active(cls, session_id: str) -> bool:
        """Interrupt an active in-process stream when a new human goal arrives."""

        active = cls._active_streams.get(session_id)
        if active is None:
            return False
        cls._superseded_sessions.add(session_id)
        provider, request_id = active
        await provider.cancel(request_id)
        return True

    async def validate(self, session_id: str, action_value: Any) -> CoordinatorAction:
        try:
            action = parse_coordinator_action(action_value)
        except ValidationError as error:
            raise CoordinatorActionRejected("malformed_coordinator_action", "Coordinator response did not match the required action format.") from error
        snapshot = await SessionConfigurationService(self._db).current(session_id)
        if isinstance(action, AssignmentsAction):
            self._validate_assignments(snapshot, action)
        if isinstance(action, FinalAction):
            await self._validate_final(session_id, snapshot)
        return action

    async def resolve_actions(self, session_id: str, actions: list[Any]) -> CoordinatorCycleResult:
        """Validate a response and at most one deterministic correction response."""

        if session_id in self._superseded_sessions:
            self._superseded_sessions.discard(session_id)
            return CoordinatorCycleResult(None, False, True, None, "user_superseded", "A newer user instruction superseded this Coordinator response.")
        for attempt, raw_action in enumerate(actions[:2]):
            if session_id in self._superseded_sessions:
                self._superseded_sessions.discard(session_id)
                return CoordinatorCycleResult(None, attempt > 0, True, None, "user_superseded", "A newer user instruction superseded this Coordinator response.")
            try:
                action = await self.validate(session_id, raw_action)
            except CoordinatorActionRejected as error:
                if attempt == 0:
                    if len(actions) == 1:
                        return CoordinatorCycleResult(None, True, False, None, error.code, error.summary)
                    continue
                resolution = (await SessionConfigurationService(self._db).current(session_id)).approval_policy["limitResolution"]
                return CoordinatorCycleResult(None, True, True, resolution, error.code, error.summary)
            return CoordinatorCycleResult(action, attempt > 0, False, None)
        resolution = (await SessionConfigurationService(self._db).current(session_id)).approval_policy["limitResolution"]
        return CoordinatorCycleResult(None, True, True, resolution, "missing_coordinator_action", "Coordinator did not provide a correction response.")

    async def execute(self, session_id: str, provider: Provider, request: ProviderRequest) -> CoordinatorCycleResult:
        """Consume structured provider output, retrying exactly once after an invalid action."""

        if session_id in self._active_streams:
            return CoordinatorCycleResult(
                None, False, True, None, "coordinator_cycle_already_active",
                "A Coordinator decision is already active for this session.",
            )
        action_values: list[Any] = []
        try:
            for attempt in range(2):
                if session_id in self._superseded_sessions:
                    await provider.cancel(request.request_id)
                    return await self.resolve_actions(session_id, action_values)
                correction_note = () if attempt == 0 else ({
                    "role": "system",
                    "content": "Your prior action was invalid. Return only one valid Coordinator action without permissions, configuration, or gate claims.",
                },)
                attempt_request = replace(
                    request,
                    request_id=f"{request.request_id}:correction:{attempt}" if attempt else request.request_id,
                    messages=(*request.messages, *correction_note),
                )
                self._active_streams[session_id] = (provider, attempt_request.request_id)
                value = await self._one_structured_output(session_id, provider, attempt_request)
                if value is _SUPERSEDED:
                    return await self.resolve_actions(session_id, action_values)
                action_values.append(value)
                result = await self.resolve_actions(session_id, action_values)
                if result.action is not None or result.stopped:
                    return result
            return await self.resolve_actions(session_id, action_values)
        finally:
            active = self._active_streams.get(session_id)
            if active is not None and active[0] is provider:
                self._active_streams.pop(session_id, None)

    async def _one_structured_output(self, session_id: str, provider: Provider, request: ProviderRequest) -> Any:
        async for event in provider.stream(request):
            if session_id in self._superseded_sessions:
                await provider.cancel(request.request_id)
                return _SUPERSEDED
            if isinstance(event, StructuredOutput):
                return event.value
            if isinstance(event, (Cancelled, RetryableError, TerminalError)):
                return {"type": "invalid_provider_result", "reason": getattr(event, "code", "cancelled")}
            if isinstance(event, Finished):
                break
            await asyncio.sleep(0)
        return {"type": "missing"}

    @staticmethod
    def _validate_assignments(snapshot: ConfigurationSnapshot, action: AssignmentsAction) -> None:
        agents = {agent["id"]: agent for agent in snapshot.agent_snapshots}
        for assignment in action.assignments:
            if assignment.assignee_agent_id not in snapshot.available_agent_ids:
                raise CoordinatorActionRejected("excluded_agent", "Coordinator selected an agent outside the available pool.")
            agent = agents.get(assignment.assignee_agent_id)
            if agent is None:
                raise CoordinatorActionRejected("unknown_agent", "Coordinator selected an unknown session agent.")
            missing = set(assignment.requested_capabilities) - set(agent["capabilities"])
            if missing:
                raise CoordinatorActionRejected("missing_capability", "Coordinator requested a capability the selected agent does not declare.")

    async def _validate_final(self, session_id: str, snapshot: ConfigurationSnapshot) -> None:
        applicable = await self._applicable_rules(session_id, snapshot)
        for rule in applicable:
            async with self._db.execute(
                """SELECT COUNT(*) AS evidence_count
                   FROM gate_evidence evidence
                   JOIN assignments assignment ON assignment.id = evidence.assignment_id
                   JOIN session_agents agent ON agent.id = assignment.assignee_session_agent_id
                   WHERE evidence.session_id = ? AND evidence.rule_id = ?
                     AND evidence.evidence_kind = ? AND evidence.validation_state = 'valid'
                     AND evidence.invalidated_at_ms IS NULL AND agent.role = ?""",
                (session_id, rule["id"], rule["successEvidence"], rule["role"]),
            ) as cursor:
                count = int((await cursor.fetchone())["evidence_count"])
            if count < rule["minimumCompletions"]:
                raise CoordinatorActionRejected("required_gate_unmet", "Coordinator cannot deliver a final result while required evidence is missing.")

    async def _applicable_rules(self, session_id: str, snapshot: ConfigurationSnapshot) -> list[dict[str, Any]]:
        has_changes = False
        used_capabilities: set[str] = set()
        async with self._db.execute(
            """SELECT event_type, payload_json FROM events
               WHERE session_id = ? AND event_type IN ('artifact.diff_updated', 'assignment.proposed')""", (session_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            # Avoid a second model-facing representation; this is a small
            # deterministic projection of the existing canonical event payload.
            payload = json.loads(row["payload_json"])
            if row["event_type"] == "artifact.diff_updated" and (payload.get("additions", 0) or payload.get("deletions", 0)):
                has_changes = True
            if row["event_type"] == "assignment.proposed":
                used_capabilities.update(str(capability) for capability in payload.get("requestedCapabilities", []))
        return [
            rule for rule in snapshot.required_role_rules
            if rule["applicability"] == "always"
            or (rule["applicability"] == "when_changes" and has_changes)
            or (rule["applicability"] == "when_capability_used" and rule["capability"] in used_capabilities)
        ]


_SUPERSEDED = object()
