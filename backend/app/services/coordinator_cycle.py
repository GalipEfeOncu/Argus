"""Deterministic validation around one structured Coordinator decision."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, ClassVar
import uuid

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
    PartialAction,
    parse_coordinator_action,
)
from app.services.assignment_scheduler import AssignmentScheduler
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

    async def persist_assignments(self, session_id: str, action: AssignmentsAction | Any) -> tuple[str, ...]:
        """Turn an already validated Coordinator action into durable scheduler work.

        Keeping this explicit makes provider execution unable to create an
        assignment by accident: validation completes before the scheduler owns
        the proposal-to-assignment transition.
        """

        raw_action = action.model_dump(by_alias=True, mode="json") if isinstance(action, AssignmentsAction) else action
        validated = await self.validate(session_id, raw_action)
        if not isinstance(validated, AssignmentsAction):
            raise CoordinatorActionRejected("not_assignment_action", "Only assignment actions can be scheduled.")
        scheduler = AssignmentScheduler(self._db)
        return tuple([
            await scheduler.accept_coordinator_proposal(session_id, proposal, parent_id=proposal.parent_id)
            for proposal in validated.assignments
        ])

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
                    if isinstance(result.action, AssignmentsAction):
                        await self.persist_assignments(session_id, result.action)
                        await AssignmentScheduler(self._db).dispatch_ready(session_id)
                    elif isinstance(result.action, PartialAction):
                        if await self.request_partial_acceptance(session_id, result.action) is None:
                            return CoordinatorCycleResult(
                                None, result.correction_requested, True, None, "partial_outcome_not_runnable",
                                "The session stopped or paused before the partial outcome could be presented.",
                            )
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
        from app.services.gate_engine import GateEngine

        gates = GateEngine(self._db)
        if any(state.status == "pending" for state in await gates.states(session_id)):
            await gates.route_unsatisfied(session_id)
            await gates.append_states(session_id)
            await AssignmentScheduler(self._db).dispatch_ready(session_id)
            raise CoordinatorActionRejected(
                "required_gate_unmet",
                "Coordinator cannot deliver a final result while required evidence is missing; eligible gate work was queued.",
            )

    async def request_partial_acceptance(self, session_id: str, action: PartialAction) -> str | None:
        """Turn a model's partial outcome into an explicit human-only decision."""

        from app.db.database import transaction
        from app.db.repositories import EventRepository, _now_ms, _safe_json

        decision_id = f"partial_{uuid.uuid4().hex}"
        request_payload = {
            "decisionId": decision_id, "scopeId": session_id, "choices": ["deliver_partial", "stop"],
            "reasonSummary": action.final_summary, "purpose": "partial_completion",
            "unmetRequirements": action.unmet_requirements,
        }
        async with transaction(self._db):
            async with self._db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)) as cursor:
                session = await cursor.fetchone()
            if session is None or session["status"] != "running":
                return None
            events = EventRepository(self._db)
            await events._append_in_transaction(
                event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="decision.requested", actor_id="system",
                payload=request_payload, payload_json=_safe_json(request_payload), timestamp_ms=_now_ms(), correlation_id=None, command_id=None,
            )
            status_payload = {"status": "waiting_decision", "reasonSummary": "Waiting for the user to accept or stop the partial outcome."}
            await events._append_in_transaction(
                event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="session.status_changed", actor_id="system",
                payload=status_payload, payload_json=_safe_json(status_payload), timestamp_ms=_now_ms(), correlation_id=decision_id, command_id=None,
            )
        return decision_id


_SUPERSEDED = object()
