"""Persist and resolve reached-limit outcomes without giving the Coordinator authority."""

from __future__ import annotations

import asyncio
import json
from typing import Any
import uuid

import aiosqlite
from pydantic import ValidationError

from app.db.database import transaction
from app.db.repositories import EventRepository, _now_ms, _safe_json
from app.providers.protocol import Finished, Provider, ProviderRequest, StructuredOutput
from app.schemas.coordinator_actions import CoordinatorLimitDecision, parse_coordinator_limit_decision
from app.schemas.coordinator_actions import coordinator_limit_decision_schema
from app.services.session_configuration_service import SessionConfigurationService


class LimitDecisionRejected(ValueError):
    """A stale, unauthorized, or budget-evading reached-limit choice."""


_CHOICES = ("reassign", "change_approach", "deliver_partial", "stop")


class LimitResolutionService:
    """A durable hand-off from a hard-limit event to exactly one resolution."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._events = EventRepository(db)

    async def request_latest_in_transaction(
        self, session_id: str, *, counter: str, scope_id: str, assignment_id: str | None = None,
        fingerprint: str | None = None, reason_summary: str = "A configured limit was reached.",
    ) -> str | None:
        """Create at most one request for the latest durable hard-limit event."""

        async with self._db.execute(
            """SELECT id FROM events WHERE session_id = ? AND event_type = 'limit.reached'
               AND json_extract(payload_json, '$.counter') = ? AND json_extract(payload_json, '$.scopeId') = ?
               ORDER BY sequence DESC LIMIT 1""",
            (session_id, counter, scope_id),
        ) as cursor:
            event = await cursor.fetchone()
        if event is None:
            return None
        return await self.request_for_event_in_transaction(
            session_id, str(event["id"]), counter=counter, scope_id=scope_id, assignment_id=assignment_id,
            fingerprint=fingerprint, reason_summary=reason_summary,
        )

    async def request_for_event_in_transaction(
        self, session_id: str, source_event_id: str, *, counter: str, scope_id: str,
        assignment_id: str | None, fingerprint: str | None, reason_summary: str,
    ) -> str:
        async with self._db.execute(
            "SELECT id FROM limit_resolution_requests WHERE source_event_id = ?", (source_event_id,)
        ) as cursor:
            existing = await cursor.fetchone()
        if existing is not None:
            return str(existing["id"])
        async with self._db.execute(
            "SELECT id FROM limit_resolution_requests WHERE session_id = ? AND state IN ('pending', 'claimed') ORDER BY created_at_ms LIMIT 1",
            (session_id,),
        ) as cursor:
            active = await cursor.fetchone()
        if active is not None:
            return str(active["id"])
        snapshot = await SessionConfigurationService(self._db).current(session_id)
        mode = str(snapshot.approval_policy["limitResolution"])
        request_id = f"limit_decision_{uuid.uuid4().hex}"
        decision_id = f"decision_{uuid.uuid4().hex}"
        now = _now_ms()
        from app.services.coordinator_cycle import CoordinatorCycle
        coordinator_available = mode == "coordinator_decides" and CoordinatorCycle.can_start_limit_decision(session_id)
        state = "stopped" if mode == "stop" or (mode == "coordinator_decides" and not coordinator_available) else "pending"
        await self._db.execute(
            """INSERT INTO limit_resolution_requests (id, session_id, source_event_id, assignment_id, counter_kind,
               scope_id, fingerprint, policy_mode, state, choices_json, decision_id, created_at_ms, resolved_at_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (request_id, session_id, source_event_id, assignment_id, counter, scope_id, fingerprint, mode, state,
             _safe_json(list(_CHOICES)), decision_id, now, now if state == "stopped" else None),
        )
        if state == "stopped":
            fallback_reason = reason_summary if mode == "stop" else "Coordinator decision context is unavailable; work stopped safely."
            await self._stop_in_transaction(session_id, assignment_id, fallback_reason)
            return request_id
        payload: dict[str, Any] = {
            "decisionId": decision_id, "scopeId": scope_id, "choices": list(_CHOICES),
            "reasonSummary": reason_summary, "purpose": "limit_resolution", "counter": counter,
        }
        if fingerprint is not None:
            payload["fingerprint"] = fingerprint
        await self._events._append_in_transaction(
            event_id=f"decision_{uuid.uuid4().hex}", session_id=session_id, event_type="decision.requested", actor_id="system",
            payload=payload, payload_json=_safe_json(payload), timestamp_ms=now, correlation_id=request_id, command_id=None,
        )
        await self._events._append_in_transaction(
            event_id=f"status_{uuid.uuid4().hex}", session_id=session_id, event_type="session.status_changed", actor_id="system",
            payload={"status": "waiting_decision", "reasonSummary": "Waiting for a bounded limit-resolution decision."},
            payload_json=_safe_json({"status": "waiting_decision", "reasonSummary": "Waiting for a bounded limit-resolution decision."}),
            timestamp_ms=now, correlation_id=request_id, command_id=None,
        )
        return request_id

    async def validate_human_choice_in_transaction(self, session_id: str, decision_id: str, choice: str) -> None:
        request = await self._pending_for_decision(session_id, decision_id)
        if request is None or request["policy_mode"] != "ask_user":
            raise LimitDecisionRejected("limit_decision_not_requested")
        await self._validate_choice(request, choice)

    async def finalize_human_choice_in_transaction(self, session_id: str, decision_id: str, choice: str, event_id: str) -> None:
        request = await self._pending_for_decision(session_id, decision_id)
        if request is None:
            raise LimitDecisionRejected("limit_decision_not_requested")
        await self._validate_choice(request, choice)
        target_state = "stopped" if choice == "stop" else "resolved"
        await self._db.execute(
            "UPDATE limit_resolution_requests SET state = ?, resolved_at_ms = ? WHERE id = ? AND state = 'pending'",
            (target_state, _now_ms(), request["id"]),
        )

    async def cancel_pending_in_transaction(self, session_id: str) -> None:
        """A human interruption wins over a late Coordinator/provider response."""

        await self._db.execute(
            "UPDATE limit_resolution_requests SET state = 'cancelled', resolved_at_ms = ? WHERE session_id = ? AND state IN ('pending', 'claimed')",
            (_now_ms(), session_id),
        )

    async def execute_coordinator_decision(
        self, session_id: str, provider: Provider, request: ProviderRequest, *, timeout_seconds: float = 20,
    ) -> CoordinatorLimitDecision | None:
        """Claim one pending request and make exactly one tool-free structured choice."""

        async with transaction(self._db):
            async with self._db.execute(
                "SELECT * FROM limit_resolution_requests WHERE session_id = ? AND policy_mode = 'coordinator_decides' AND state = 'pending' ORDER BY created_at_ms LIMIT 1",
                (session_id,),
            ) as cursor:
                pending = await cursor.fetchone()
            if pending is None:
                return None
            await self._db.execute("UPDATE limit_resolution_requests SET state = 'claimed' WHERE id = ?", (pending["id"],))
        safe_request = ProviderRequest(
            request_id=f"{request.request_id}:limit-decision", model_id=request.model_id, messages=request.messages,
            tools=(), response_schema=coordinator_limit_decision_schema(), metadata={"purpose": "limit_resolution"},
        )
        try:
            value = await asyncio.wait_for(self._one_structured_output(provider, safe_request), timeout_seconds)
            decision = parse_coordinator_limit_decision(value)
        except (asyncio.TimeoutError, ValidationError, ValueError):
            await self._finish_coordinator_decision(session_id, str(pending["id"]), "stop", "Coordinator limit decision timed out or was malformed.", timed_out=True)
            return None
        await self._finish_coordinator_decision(session_id, str(pending["id"]), decision.choice, decision.reason_summary)
        if decision.choice in {"reassign", "change_approach"}:
            await self.replan_after_resolution(session_id, str(pending["decision_id"]))
        return decision

    async def _one_structured_output(self, provider: Provider, request: ProviderRequest) -> Any:
        async for event in provider.stream(request):
            if isinstance(event, StructuredOutput):
                return event.value
            if isinstance(event, Finished):
                break
        raise ValueError("missing coordinator limit decision")

    async def _finish_coordinator_decision(
        self, session_id: str, request_id: str, choice: str, reason: str, *, timed_out: bool = False,
    ) -> None:
        async with transaction(self._db):
            async with self._db.execute("SELECT * FROM limit_resolution_requests WHERE id = ? AND session_id = ? AND state = 'claimed'", (request_id, session_id)) as cursor:
                pending = await cursor.fetchone()
            if pending is None:
                return
            async with self._db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)) as cursor:
                session = await cursor.fetchone()
            if session is None or session["status"] != "waiting_decision":
                await self._db.execute("UPDATE limit_resolution_requests SET state = 'cancelled', resolved_at_ms = ? WHERE id = ?", (_now_ms(), request_id))
                return
            try:
                await self._validate_choice(pending, choice)
            except LimitDecisionRejected:
                choice, reason, timed_out = "stop", "Coordinator choice could not satisfy the remaining deterministic limits.", True
            event = await self._events._append_in_transaction(
                event_id=f"decision_{uuid.uuid4().hex}", session_id=session_id, event_type="decision.recorded", actor_id="coordinator",
                payload={"decisionId": pending["decision_id"], "choice": choice, "reasonSummary": reason},
                payload_json=_safe_json({"decisionId": pending["decision_id"], "choice": choice, "reasonSummary": reason}),
                timestamp_ms=_now_ms(), correlation_id=request_id, command_id=None,
            )
            if choice == "stop":
                await self._stop_in_transaction(session_id, pending["assignment_id"], reason)
                state = "timed_out" if timed_out else "stopped"
            elif choice == "deliver_partial":
                partial_id = f"partial_{uuid.uuid4().hex}"
                partial_payload = {
                    "decisionId": partial_id, "scopeId": pending["scope_id"], "choices": ["deliver_partial", "stop"],
                    "reasonSummary": reason, "purpose": "partial_completion", "unmetRequirements": ["A reached limit prevented further full completion."],
                }
                await self._events._append_in_transaction(
                    event_id=f"decision_{uuid.uuid4().hex}", session_id=session_id, event_type="decision.requested", actor_id="system",
                    payload=partial_payload, payload_json=_safe_json(partial_payload), timestamp_ms=_now_ms(),
                    correlation_id=event.event_id, command_id=None,
                )
                # The Coordinator only proposes a partial outcome.  The human
                # receives this separate durable request and must accept it.
                state = "resolved"
            else:
                await self._events._append_in_transaction(
                    event_id=f"status_{uuid.uuid4().hex}", session_id=session_id, event_type="session.status_changed", actor_id="system",
                    payload={"status": "running", "reasonSummary": "Coordinator applied a bounded limit-resolution choice."},
                    payload_json=_safe_json({"status": "running", "reasonSummary": "Coordinator applied a bounded limit-resolution choice."}),
                    timestamp_ms=_now_ms(), correlation_id=event.event_id, command_id=None,
                )
                state = "resolved"
            await self._db.execute("UPDATE limit_resolution_requests SET state = ?, resolved_at_ms = ? WHERE id = ?", (state, _now_ms(), request_id))

    async def _pending_for_decision(self, session_id: str, decision_id: str) -> aiosqlite.Row | None:
        async with self._db.execute(
            "SELECT * FROM limit_resolution_requests WHERE session_id = ? AND decision_id = ? AND state = 'pending'",
            (session_id, decision_id),
        ) as cursor:
            return await cursor.fetchone()

    async def _validate_choice(self, request: aiosqlite.Row, choice: str) -> None:
        if choice not in json.loads(request["choices_json"]):
            raise LimitDecisionRejected("limit_decision_choice_forbidden")
        if choice not in {"reassign", "change_approach"}:
            return
        if request["counter_kind"] not in {"repeated_finding", "repeated_failure", "no_progress"}:
            raise LimitDecisionRejected("hard_ceiling_cannot_be_evaded")
        if request["assignment_id"] is None:
            raise LimitDecisionRejected("no_remaining_assignee")
        async with self._db.execute(
            """SELECT proposal.proposal_json, assignment.assignee_session_agent_id FROM assignments assignment
               JOIN assignment_proposals proposal ON proposal.assignment_id = assignment.id
               WHERE assignment.id = ? AND assignment.session_id = ?""",
            (request["assignment_id"], request["session_id"]),
        ) as cursor:
            assignment = await cursor.fetchone()
        if assignment is None:
            raise LimitDecisionRejected("no_remaining_assignee")
        snapshot = await SessionConfigurationService(self._db).current(str(request["session_id"]))
        ceiling = snapshot.execution_limits.get("maxAssignmentAttempts")
        if ceiling is not None:
            async with self._db.execute("SELECT COUNT(*) AS total FROM assignment_attempts WHERE assignment_id = ?", (request["assignment_id"],)) as cursor:
                if int((await cursor.fetchone())["total"]) >= int(ceiling):
                    raise LimitDecisionRejected("remaining_assignment_budget_exhausted")
        source_proposal = json.loads(assignment["proposal_json"])
        finding = source_proposal.get("findingFingerprint")
        revision_ceiling = snapshot.execution_limits.get("maxRevisionsPerFinding")
        if isinstance(finding, str) and revision_ceiling is not None:
            async with self._db.execute(
                "SELECT consumed_real FROM limit_counters WHERE session_id = ? AND counter_kind = 'revisions' AND scope_type = 'finding' AND scope_id = ?",
                (request["session_id"], finding),
            ) as cursor:
                revision = await cursor.fetchone()
            if revision is not None and float(revision["consumed_real"]) >= float(revision_ceiling):
                raise LimitDecisionRejected("hard_ceiling_cannot_be_evaded")
        requested = set(source_proposal.get("requestedCapabilities", []))
        eligible = [agent for agent in snapshot.agent_snapshots if agent["id"] in snapshot.available_agent_ids and agent["id"] != assignment["assignee_session_agent_id"] and requested <= set(agent["capabilities"])]
        if not eligible:
            raise LimitDecisionRejected("no_remaining_assignee")

    async def replan_after_resolution(self, session_id: str, decision_id: str) -> str | None:
        """Create one validated replacement assignment after a bounded choice."""

        async with self._db.execute(
            "SELECT * FROM limit_resolution_requests WHERE session_id = ? AND decision_id = ? AND state = 'resolved'",
            (session_id, decision_id),
        ) as cursor:
            request = await cursor.fetchone()
        if request is None or request["assignment_id"] is None:
            return None
        async with self._db.execute(
            """SELECT payload_json FROM events WHERE session_id = ? AND event_type = 'decision.recorded'
               AND json_extract(payload_json, '$.decisionId') = ? ORDER BY sequence DESC LIMIT 1""",
            (session_id, decision_id),
        ) as cursor:
            decision_event = await cursor.fetchone()
        if decision_event is None or json.loads(decision_event["payload_json"]).get("choice") not in {"reassign", "change_approach"}:
            return None
        async with self._db.execute(
            """SELECT proposal.proposal_json, assignment.assignee_session_agent_id FROM assignments assignment
               JOIN assignment_proposals proposal ON proposal.assignment_id = assignment.id
               WHERE assignment.id = ? AND assignment.session_id = ?""",
            (request["assignment_id"], session_id),
        ) as cursor:
            source = await cursor.fetchone()
        if source is None:
            return None
        raw = json.loads(source["proposal_json"])
        snapshot = await SessionConfigurationService(self._db).current(session_id)
        requested = set(raw.get("requestedCapabilities", []))
        candidates = [agent for agent in snapshot.agent_snapshots if agent["id"] in snapshot.available_agent_ids and agent["id"] != source["assignee_session_agent_id"] and requested <= set(agent["capabilities"])]
        if not candidates:
            return None
        from app.schemas.coordinator_actions import CoordinatorAssignment
        from app.services.assignment_scheduler import AssignmentScheduler
        proposal = CoordinatorAssignment.model_validate({
            **raw, "proposalId": f"replan_{uuid.uuid4().hex}", "assigneeAgentId": candidates[0]["id"],
            "parentId": None, "reasonSummary": "A bounded limit decision selected a remaining eligible assignee.",
        })
        scheduler = AssignmentScheduler(self._db)
        await scheduler.cancel_assignment(session_id, str(request["assignment_id"]), reason="Reassigned after a bounded limit decision.")
        try:
            assignment_id = await scheduler.accept_coordinator_proposal(session_id, proposal)
            await scheduler.dispatch_ready(session_id)
            return assignment_id
        except Exception:
            # A concurrent counter/lease update is authoritative; the already
            # recorded decision remains auditable but cannot start replacement work.
            return None

    async def _stop_in_transaction(self, session_id: str, assignment_id: str | None, reason: str) -> None:
        now = _now_ms()
        async with self._db.execute(
            "SELECT id, state, writer_lease_id FROM assignments WHERE session_id = ? AND state IN ('created', 'running')",
            (session_id,),
        ) as cursor:
            active_assignments = await cursor.fetchall()
        for assignment in active_assignments:
            active_id = str(assignment["id"])
            event = await self._events._append_in_transaction(
                    event_id=f"failed_{uuid.uuid4().hex}", session_id=session_id, event_type="assignment.failed", actor_id="system",
                    payload={"assignmentId": active_id, "failureCode": "limit_reached", "failureSummary": reason, "recoverable": False},
                    payload_json=_safe_json({"assignmentId": active_id, "failureCode": "limit_reached", "failureSummary": reason, "recoverable": False}),
                    timestamp_ms=now, correlation_id=None, command_id=None,
            )
            await self._db.execute("UPDATE assignments SET state = 'failed', terminal_event_id = ?, updated_at_ms = ? WHERE id = ?", (event.event_id, now, active_id))
            await self._db.execute("UPDATE assignment_attempts SET state = 'failed', completed_at_ms = ?, updated_at_ms = ? WHERE assignment_id = ? AND state = 'running'", (now, now, active_id))
            from app.services.budget_counter_service import BudgetCounterService
            await BudgetCounterService(self._db).release_assignment_capacity(active_id)
            if assignment["writer_lease_id"] is not None:
                await self._db.execute("UPDATE writer_leases SET released_at_ms = ?, release_reason = 'limit_reached' WHERE id = ? AND released_at_ms IS NULL", (now, assignment["writer_lease_id"]))
                await self._db.execute("UPDATE projects SET lock_session_id = NULL, lock_acquired_at_ms = NULL, updated_at_ms = ? WHERE lock_session_id = ?", (now, session_id))
        await self._events._append_in_transaction(
            event_id=f"status_{uuid.uuid4().hex}", session_id=session_id, event_type="session.status_changed", actor_id="system",
            payload={"status": "failed", "reasonSummary": reason}, payload_json=_safe_json({"status": "failed", "reasonSummary": reason}),
            timestamp_ms=now, correlation_id=None, command_id=None,
        )
