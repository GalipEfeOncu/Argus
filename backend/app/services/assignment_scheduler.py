"""Durable, policy-enforcing assignment scheduler.

The scheduler is the only service that turns a model proposal into executable
work.  Its state is entirely reconstructable from SQLite: worker processes and
in-memory tasks are deliberately only execution details.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
import uuid

import aiosqlite

from app.db.database import transaction
from app.db.repositories import EventRepository, StoredEvent, _now_ms, _safe_json
from app.schemas.coordinator_actions import CoordinatorAssignment
from app.services.session_configuration_service import ConfigurationSnapshot, SessionConfigurationService


class SchedulerRejected(ValueError):
    """A proposal or lifecycle request rejected by deterministic policy."""

    def __init__(self, code: str, summary: str) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary


@dataclass(frozen=True)
class ScheduledAssignment:
    assignment_id: str
    proposal_id: str
    attempt_id: str
    operation_class: str
    writer_lease_id: str | None


class AssignmentScheduler:
    """Persist proposals, dispatch bounded work, and recover interrupted work."""

    def __init__(self, db: aiosqlite.Connection, *, writer_lease_ttl_ms: int = 60_000) -> None:
        if writer_lease_ttl_ms < 1_000:
            raise ValueError("writer_lease_ttl_ms must be at least 1000ms")
        self._db = db
        self._events = EventRepository(db)
        self._writer_lease_ttl_ms = writer_lease_ttl_ms

    async def accept_coordinator_proposal(
        self, session_id: str, proposal: CoordinatorAssignment, *, parent_id: str | None = None,
    ) -> str:
        """Validate and durably accept one Coordinator proposal exactly once."""

        raw = proposal.model_dump(by_alias=True, mode="json")
        rejection: SchedulerRejected | None = None
        assignment_id: str | None = None
        async with transaction(self._db):
            existing = await self._proposal_assignment(session_id, proposal.proposal_id)
            if existing is not None:
                if existing["validation_state"] != "accepted":
                    raise SchedulerRejected(str(existing["validation_code"] or "proposal_rejected"), "Proposal was previously rejected.")
                return str(existing["assignment_id"])
            snapshot = await SessionConfigurationService(self._db).current(session_id)
            proposed = await self._event(
                session_id, "assignment.proposed", "coordinator", {
                    "proposalId": proposal.proposal_id, "assigneeAgentId": proposal.assignee_agent_id,
                    **({"parentId": parent_id} if parent_id is not None else {}),
                    "objective": proposal.objective, "acceptanceCriteria": proposal.acceptance_criteria,
                    "operationClass": proposal.operation_class, "requestedCapabilities": proposal.requested_capabilities,
                    "reasonSummary": proposal.reason_summary,
                },
            )
            now = _now_ms()
            try:
                await self._validate_proposal(session_id, snapshot, proposal, parent_id)
            except SchedulerRejected as error:
                rejection = error
                resolved = await self._event(session_id, "error.created", "system", {
                    "errorId": f"proposal_{proposal.proposal_id}", "code": error.code,
                    "summary": error.summary, "recoverable": True,
                })
                await self._db.execute(
                    """INSERT INTO assignment_proposals (id, session_id, parent_assignment_id, actor_id, proposal_json,
                       validation_state, validation_code, proposed_event_id, resolved_event_id, created_at_ms)
                       VALUES (?, ?, ?, 'coordinator', ?, 'rejected', ?, ?, ?, ?)""",
                    (proposal.proposal_id, session_id, parent_id, _safe_json(raw), error.code,
                     proposed.event_id, resolved.event_id, now),
                )
            else:
                assignment_id = f"asn_{uuid.uuid4().hex}"
                created = await self._event(
                    session_id, "assignment.created", "system", {
                        "assignmentId": assignment_id, "proposalId": proposal.proposal_id,
                        "assigneeAgentId": proposal.assignee_agent_id, "configurationVersion": snapshot.version,
                        "policyHash": snapshot.policy_hash, "operationClass": proposal.operation_class,
                    },
                )
                await self._db.execute(
                    """INSERT INTO assignments (id, session_id, parent_id, assignee_session_agent_id, state,
                       operation_class, acceptance_criteria_json, budget_json, configuration_version,
                       created_event_id, created_at_ms, updated_at_ms)
                       VALUES (?, ?, ?, ?, 'created', ?, ?, ?, ?, ?, ?, ?)""",
                    (assignment_id, session_id, parent_id, proposal.assignee_agent_id, proposal.operation_class,
                     _safe_json(proposal.acceptance_criteria), _safe_json(proposal.requested_budget), snapshot.version,
                     created.event_id, now, now),
                )
                await self._db.execute(
                    """INSERT INTO assignment_proposals (id, session_id, parent_assignment_id, actor_id, proposal_json,
                       validation_state, assignment_id, proposed_event_id, resolved_event_id, created_at_ms)
                       VALUES (?, ?, ?, 'coordinator', ?, 'accepted', ?, ?, ?, ?)""",
                    (proposal.proposal_id, session_id, parent_id, _safe_json(raw), assignment_id,
                     proposed.event_id, created.event_id, now),
                )
        if rejection is not None:
            raise rejection
        assert assignment_id is not None
        return assignment_id

    async def propose_follow_up(
        self, session_id: str, source_assignment_id: str, proposal: CoordinatorAssignment,
        *, summary: str, artifact_ids: list[str] | None = None,
    ) -> str:
        """Record a specialist follow-up and route it to the Coordinator by default."""

        artifact_ids = artifact_ids or []
        async with transaction(self._db):
            source = await self._assignment(session_id, source_assignment_id)
            if source is None:
                raise SchedulerRejected("unknown_assignment", "Follow-up source assignment does not exist.")
            if source["state"] not in {"running", "completed"}:
                raise SchedulerRejected("source_assignment_inactive", "Only an active or completed assignment can propose a handoff.")
            handoff_id = f"handoff_{uuid.uuid4().hex}"
            event = await self._event(session_id, "handoff.created", str(source["assignee_session_agent_id"]), {
                "handoffId": handoff_id, "sourceAssignmentId": source_assignment_id,
                "targetAgentId": proposal.assignee_agent_id, "summary": summary, "artifactIds": artifact_ids,
            })
            now = _now_ms()
            await self._db.execute(
                """INSERT INTO assignment_handoffs (id, session_id, source_assignment_id, target_agent_id, summary,
                   artifact_ids_json, follow_up_proposal_json, state, event_id, created_at_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'routed_to_coordinator', ?, ?)""",
                (handoff_id, session_id, source_assignment_id, proposal.assignee_agent_id, summary,
                 _safe_json(artifact_ids), _safe_json(proposal.model_dump(by_alias=True, mode="json")), event.event_id, now),
            )
            return handoff_id

    async def dispatch_ready(self, session_id: str) -> tuple[ScheduledAssignment, ...]:
        """Start eligible work, allowing bounded parallel readers and one writer."""

        async with transaction(self._db):
            async with self._db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)) as cursor:
                session = await cursor.fetchone()
            if session is None:
                raise SchedulerRejected("session_not_found", "Session does not exist.")
            if session["status"] != "running":
                return ()
            snapshot = await SessionConfigurationService(self._db).current(session_id)
            limit = snapshot.execution_limits.get("maxParallelReadOnlyAssignments")
            read_limit = 3 if limit is None else int(limit)
            async with self._db.execute(
                "SELECT COUNT(*) AS total FROM assignments WHERE session_id = ? AND state = 'running' AND operation_class = 'read_only'",
                (session_id,),
            ) as cursor:
                active_readers = int((await cursor.fetchone())["total"])
            async with self._db.execute(
                "SELECT 1 FROM assignments WHERE session_id = ? AND state = 'running' AND operation_class = 'mutating' LIMIT 1",
                (session_id,),
            ) as cursor:
                writer_running = await cursor.fetchone() is not None
            async with self._db.execute(
                "SELECT * FROM assignments WHERE session_id = ? AND state = 'created' ORDER BY created_at_ms, rowid", (session_id,)
            ) as cursor:
                pending = await cursor.fetchall()
            started: list[ScheduledAssignment] = []
            for row in pending:
                if row["operation_class"] == "read_only":
                    if active_readers >= read_limit:
                        continue
                    lease_id = None
                    active_readers += 1
                else:
                    if writer_running:
                        continue
                    try:
                        lease_id = await self._acquire_writer_lease(session_id, str(row["id"]))
                    except SchedulerRejected:
                        # Another session may own the project lock. Leave this
                        # assignment queued; do not discard readers already
                        # started in this transaction.
                        continue
                    writer_running = True
                attempt_id = f"att_{uuid.uuid4().hex}"
                now = _now_ms()
                await self._db.execute(
                    "UPDATE assignments SET state = 'running', writer_lease_id = ?, updated_at_ms = ? WHERE id = ?",
                    (lease_id, now, row["id"]),
                )
                await self._db.execute(
                    """INSERT INTO assignment_attempts (id, assignment_id, attempt_number, configuration_version,
                       checkpoint_json, usage_json, normalized_outcome_json, state, request_id, started_at_ms, updated_at_ms)
                       SELECT ?, id, COALESCE((SELECT MAX(attempt_number) + 1 FROM assignment_attempts WHERE assignment_id = assignments.id), 1),
                              configuration_version, '{}', '{}', '{}', 'running', ?, ?, ?
                       FROM assignments WHERE id = ?""",
                    (attempt_id, f"worker_{attempt_id}", now, now, row["id"]),
                )
                await self._event(session_id, "assignment.started", "system", {
                    "assignmentId": row["id"], "assigneeAgentId": row["assignee_session_agent_id"],
                })
                started.append(ScheduledAssignment(str(row["id"]), await self._proposal_id(str(row["id"])), attempt_id, str(row["operation_class"]), lease_id))
            return tuple(started)

    async def checkpoint(self, attempt_id: str, checkpoint: dict[str, Any]) -> None:
        async with transaction(self._db):
            async with self._db.execute("SELECT assignment.* FROM assignment_attempts attempt JOIN assignments assignment ON assignment.id = attempt.assignment_id WHERE attempt.id = ?", (attempt_id,)) as cursor:
                assignment = await cursor.fetchone()
            if assignment is None:
                raise SchedulerRejected("attempt_not_running", "Checkpoint requires a running attempt.")
            async with self._db.execute("SELECT session_id FROM assignments WHERE id = ?", (assignment["id"],)) as cursor:
                session_row = await cursor.fetchone()
            assert session_row is not None
            await self._require_assignment_runnable(str(session_row["session_id"]), assignment)
            await self._require_active_writer_lease(assignment)
            cursor = await self._db.execute(
                "UPDATE assignment_attempts SET checkpoint_json = ?, updated_at_ms = ? WHERE id = ? AND state = 'running'",
                (_safe_json(checkpoint), _now_ms(), attempt_id),
            )
            if cursor.rowcount != 1:
                raise SchedulerRejected("attempt_not_running", "Checkpoint requires a running attempt.")

    async def complete_attempt(
        self, session_id: str, attempt_id: str, *, output_summary: str, evidence: list[dict[str, Any]] | None = None,
    ) -> None:
        evidence = evidence or []
        async with transaction(self._db):
            attempt, assignment = await self._attempt_assignment(session_id, attempt_id)
            if attempt is None or assignment is None or attempt["state"] != "running":
                raise SchedulerRejected("attempt_not_running", "Only a running attempt can complete.")
            await self._require_assignment_runnable(session_id, assignment)
            await self._require_active_writer_lease(assignment)
            event = await self._event(session_id, "assignment.completed", str(assignment["assignee_session_agent_id"]), {
                "assignmentId": assignment["id"], "status": "completed", "outputSummary": output_summary, "evidence": evidence,
            })
            now = _now_ms()
            await self._db.execute("UPDATE assignment_attempts SET state = 'completed', normalized_outcome_json = ?, completed_at_ms = ?, updated_at_ms = ? WHERE id = ?", (_safe_json({"status": "completed", "summary": output_summary}), now, now, attempt_id))
            await self._db.execute("UPDATE assignments SET state = 'completed', terminal_event_id = ?, updated_at_ms = ? WHERE id = ?", (event.event_id, now, assignment["id"]))
            from app.services.gate_engine import GateEngine
            await GateEngine(self._db).record_evidence(session_id, assignment, evidence)
            await self._release_assignment_lease(assignment, "completed")

    async def fail_attempt(
        self, session_id: str, attempt_id: str, *, code: str, summary: str, recoverable: bool,
    ) -> bool:
        """Record a failure and queue a bounded retry when policy permits it."""

        async with transaction(self._db):
            attempt, assignment = await self._attempt_assignment(session_id, attempt_id)
            if attempt is None or assignment is None or attempt["state"] != "running":
                raise SchedulerRejected("attempt_not_running", "Only a running attempt can fail.")
            await self._require_assignment_runnable(session_id, assignment)
            await self._require_active_writer_lease(assignment)
            snapshot = await SessionConfigurationService(self._db).current(session_id)
            ceiling = snapshot.execution_limits.get("maxAssignmentAttempts")
            retry = recoverable and (ceiling is None or int(attempt["attempt_number"]) < int(ceiling))
            event = await self._event(session_id, "assignment.failed", str(assignment["assignee_session_agent_id"]), {
                "assignmentId": assignment["id"], "failureCode": code, "failureSummary": summary, "recoverable": retry,
            })
            now = _now_ms()
            await self._db.execute("UPDATE assignment_attempts SET state = 'failed', failure_fingerprint = ?, normalized_outcome_json = ?, completed_at_ms = ?, updated_at_ms = ? WHERE id = ?", (code, _safe_json({"status": "failed", "code": code}), now, now, attempt_id))
            await self._db.execute("UPDATE assignments SET state = ?, terminal_event_id = ?, updated_at_ms = ? WHERE id = ?", ("created" if retry else "failed", None if retry else event.event_id, now, assignment["id"]))
            await self._release_assignment_lease(assignment, "retry" if retry else "failed")
            return retry

    async def cancel_assignment(self, session_id: str, assignment_id: str, *, reason: str) -> tuple[str, ...]:
        """Cancel an assignment and all non-terminal descendants before more output can commit."""

        async with transaction(self._db):
            ids = await self._descendants(session_id, assignment_id)
            if not ids:
                raise SchedulerRejected("unknown_assignment", "Assignment does not exist.")
            cancelled: list[str] = []
            for item_id in reversed(ids):
                row = await self._assignment(session_id, item_id)
                assert row is not None
                if row["state"] in {"completed", "failed", "cancelled"}:
                    continue
                event = await self._event(session_id, "assignment.cancelled", "system", {"assignmentId": item_id, "reasonSummary": reason})
                now = _now_ms()
                await self._db.execute("UPDATE assignments SET state = 'cancelled', terminal_event_id = ?, updated_at_ms = ? WHERE id = ?", (event.event_id, now, item_id))
                await self._db.execute("UPDATE assignment_attempts SET state = 'cancelled', completed_at_ms = ?, updated_at_ms = ? WHERE assignment_id = ? AND state = 'running'", (now, now, item_id))
                await self._release_assignment_lease(row, "cancelled")
                cancelled.append(item_id)
            return tuple(cancelled)

    async def interrupt_participant(self, session_id: str, participant_id: str, *, reason: str) -> tuple[str, ...]:
        """Propagate a participant interrupt to every active assignment it owns."""

        async with self._db.execute(
            """SELECT id FROM assignments WHERE session_id = ? AND assignee_session_agent_id = ?
               AND state IN ('created', 'running') ORDER BY created_at_ms""", (session_id, participant_id)
        ) as cursor:
            assignment_ids = [str(row["id"]) for row in await cursor.fetchall()]
        interrupted: list[str] = []
        for assignment_id in assignment_ids:
            interrupted.extend(await self.cancel_assignment(session_id, assignment_id, reason=reason))
        return tuple(dict.fromkeys(interrupted))

    async def cancel_session(self, session_id: str, *, reason: str) -> tuple[str, ...]:
        """Cancel all active work in a session, releasing each writer lease."""

        async with self._db.execute(
            "SELECT id FROM assignments WHERE session_id = ? AND state IN ('created', 'running') ORDER BY created_at_ms", (session_id,)
        ) as cursor:
            assignment_ids = [str(row["id"]) for row in await cursor.fetchall()]
        cancelled: list[str] = []
        for assignment_id in assignment_ids:
            cancelled.extend(await self.cancel_assignment(session_id, assignment_id, reason=reason))
        return tuple(dict.fromkeys(cancelled))

    async def recover_orphaned_attempts(self, session_id: str) -> tuple[str, ...]:
        """Turn attempts left running by a sidecar crash into safely retryable work."""

        async with transaction(self._db):
            async with self._db.execute(
                """SELECT attempt.id AS attempt_id, attempt.attempt_number, assignment.* FROM assignment_attempts attempt
                   JOIN assignments assignment ON assignment.id = attempt.assignment_id
                   WHERE assignment.session_id = ? AND attempt.state = 'running'""", (session_id,)
            ) as cursor:
                rows = await cursor.fetchall()
            recovered: list[str] = []
            snapshot = await SessionConfigurationService(self._db).current(session_id)
            ceiling = snapshot.execution_limits.get("maxAssignmentAttempts")
            for row in rows:
                now = _now_ms()
                await self._db.execute("UPDATE assignment_attempts SET state = 'orphaned', completed_at_ms = ?, updated_at_ms = ? WHERE id = ?", (now, now, row["attempt_id"]))
                exhausted = ceiling is not None and int(row["attempt_number"]) >= int(ceiling)
                if exhausted:
                    event = await self._event(session_id, "assignment.failed", "system", {
                        "assignmentId": row["id"], "failureCode": "worker_orphaned",
                        "failureSummary": "Worker stopped before recording a result and retry budget is exhausted.", "recoverable": False,
                    })
                    await self._db.execute("UPDATE assignments SET state = 'failed', terminal_event_id = ?, writer_lease_id = NULL, updated_at_ms = ? WHERE id = ?", (event.event_id, now, row["id"]))
                else:
                    await self._db.execute("UPDATE assignments SET state = 'created', writer_lease_id = NULL, updated_at_ms = ? WHERE id = ?", (now, row["id"]))
                await self._release_assignment_lease(row, "orphaned_recovery")
                recovered.append(str(row["attempt_id"]))
            return tuple(recovered)

    async def _validate_proposal(self, session_id: str, snapshot: ConfigurationSnapshot, proposal: CoordinatorAssignment, parent_id: str | None) -> None:
        if proposal.assignee_agent_id not in snapshot.available_agent_ids:
            raise SchedulerRejected("excluded_agent", "The proposed agent is outside the available pool.")
        if parent_id is not None and not parent_id:
            raise SchedulerRejected("invalid_parent", "Parent assignment must be non-empty.")
        if parent_id is not None:
            parent = await self._assignment(session_id, parent_id)
            if parent is None or parent["state"] in {"completed", "failed", "cancelled", "interrupted"}:
                raise SchedulerRejected("invalid_parent", "Parent assignment must be active and belong to this session.")
        agents = {agent["id"]: agent for agent in snapshot.agent_snapshots}
        agent = agents.get(proposal.assignee_agent_id)
        if agent is None:
            raise SchedulerRejected("unknown_agent", "The proposed agent does not belong to this session.")
        if set(proposal.requested_capabilities) - set(agent["capabilities"]):
            raise SchedulerRejected("missing_capability", "The proposed agent lacks a requested capability.")
        if proposal.operation_class == "mutating" and "workspace.write" not in proposal.requested_capabilities:
            raise SchedulerRejected("writer_capability_required", "Mutating work must explicitly request workspace.write.")
        if proposal.requested_capabilities and not await self._has_grant(session_id, snapshot, proposal.requested_capabilities):
            raise SchedulerRejected("permission_grant_required", "The requested capabilities do not have an active policy grant.")

    async def _has_grant(self, session_id: str, snapshot: ConfigurationSnapshot, capabilities: list[str]) -> bool:
        policy = snapshot.approval_policy
        requested = set(capabilities)
        if policy["behavior"] == "preauthorize_session":
            return requested <= set(policy["preauthorizedCapabilities"])
        if policy["behavior"] == "deny_interactive":
            return False
        async with self._db.execute(
            "SELECT capability FROM approvals WHERE session_id = ? AND decision IN ('approved', 'granted') AND (grant_expires_at_ms IS NULL OR grant_expires_at_ms > ?)",
            (session_id, _now_ms()),
        ) as cursor:
            granted = {str(row["capability"]) for row in await cursor.fetchall()}
        return requested <= granted

    async def _acquire_writer_lease(self, session_id: str, assignment_id: str) -> str:
        now = _now_ms()
        async with self._db.execute("SELECT project_id FROM workspaces WHERE session_id = ? AND cleaned_at_ms IS NULL", (session_id,)) as cursor:
            workspace = await cursor.fetchone()
        if workspace is None:
            raise SchedulerRejected("workspace_unavailable", "Mutating work requires an active session workspace.")
        project_id = str(workspace["project_id"])
        await self._db.execute("UPDATE writer_leases SET released_at_ms = ?, release_reason = 'expired_recovery' WHERE project_id = ? AND released_at_ms IS NULL AND expires_at_ms <= ?", (now, project_id, now))
        async with self._db.execute("SELECT id FROM writer_leases WHERE project_id = ? AND released_at_ms IS NULL LIMIT 1", (project_id,)) as cursor:
            active = await cursor.fetchone()
        if active is not None:
            raise SchedulerRejected("writer_lease_unavailable", "Another mutating assignment holds the writer lease.")
        lease_id = f"lease_{uuid.uuid4().hex}"
        await self._db.execute("INSERT INTO writer_leases (id, project_id, session_id, holder_id, acquired_at_ms, expires_at_ms, renewed_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?)", (lease_id, project_id, session_id, assignment_id, now, now + self._writer_lease_ttl_ms, now))
        await self._db.execute("UPDATE projects SET lock_session_id = ?, lock_acquired_at_ms = ?, updated_at_ms = ? WHERE id = ?", (session_id, now, now, project_id))
        return lease_id

    async def _release_assignment_lease(self, assignment: aiosqlite.Row, reason: str) -> None:
        lease_id = assignment["writer_lease_id"]
        if lease_id is None:
            return
        now = _now_ms()
        async with self._db.execute("SELECT project_id, session_id FROM writer_leases WHERE id = ? AND released_at_ms IS NULL", (lease_id,)) as cursor:
            lease = await cursor.fetchone()
        if lease is None:
            return
        await self._db.execute("UPDATE writer_leases SET released_at_ms = ?, release_reason = ? WHERE id = ?", (now, reason, lease_id))
        await self._db.execute("UPDATE projects SET lock_session_id = NULL, lock_acquired_at_ms = NULL, updated_at_ms = ? WHERE id = ? AND lock_session_id = ?", (now, lease["project_id"], lease["session_id"]))

    async def _require_active_writer_lease(self, assignment: aiosqlite.Row) -> None:
        lease_id = assignment["writer_lease_id"]
        if lease_id is None:
            return
        async with self._db.execute(
            "SELECT 1 FROM writer_leases WHERE id = ? AND holder_id = ? AND released_at_ms IS NULL AND expires_at_ms > ?",
            (lease_id, assignment["id"], _now_ms()),
        ) as cursor:
            active = await cursor.fetchone()
        if active is None:
            raise SchedulerRejected("writer_lease_lost", "The writer lease is no longer active; worker output was discarded.")

    async def _require_assignment_runnable(self, session_id: str, assignment: aiosqlite.Row) -> None:
        async with self._db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)) as cursor:
            session = await cursor.fetchone()
        if session is None or session["status"] != "running" or assignment["state"] != "running":
            raise SchedulerRejected("assignment_cancelled", "Worker output was discarded because the assignment is no longer running.")

    async def _event(self, session_id: str, event_type: str, actor_id: str, payload: dict[str, Any]) -> StoredEvent:
        return await self._events._append_in_transaction(event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type=event_type, actor_id=actor_id, payload=payload, payload_json=_safe_json(payload), timestamp_ms=_now_ms(), correlation_id=None, command_id=None)

    async def _proposal_assignment(self, session_id: str, proposal_id: str) -> aiosqlite.Row | None:
        async with self._db.execute("SELECT * FROM assignment_proposals WHERE session_id = ? AND id = ?", (session_id, proposal_id)) as cursor:
            return await cursor.fetchone()

    async def _proposal_id(self, assignment_id: str) -> str:
        async with self._db.execute("SELECT id FROM assignment_proposals WHERE assignment_id = ?", (assignment_id,)) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        return str(row["id"])

    async def _assignment(self, session_id: str, assignment_id: str) -> aiosqlite.Row | None:
        async with self._db.execute("SELECT * FROM assignments WHERE session_id = ? AND id = ?", (session_id, assignment_id)) as cursor:
            return await cursor.fetchone()

    async def _attempt_assignment(self, session_id: str, attempt_id: str) -> tuple[aiosqlite.Row | None, aiosqlite.Row | None]:
        async with self._db.execute("SELECT attempt.*, assignment.id AS assignment_id_value FROM assignment_attempts attempt JOIN assignments assignment ON assignment.id = attempt.assignment_id WHERE attempt.id = ? AND assignment.session_id = ?", (attempt_id, session_id)) as cursor:
            attempt = await cursor.fetchone()
        if attempt is None:
            return None, None
        assignment = await self._assignment(session_id, str(attempt["assignment_id_value"]))
        return attempt, assignment

    async def _descendants(self, session_id: str, assignment_id: str) -> list[str]:
        async with self._db.execute("""WITH RECURSIVE tree(id) AS (
              SELECT id FROM assignments WHERE session_id = ? AND id = ?
              UNION ALL SELECT assignment.id FROM assignments assignment JOIN tree ON assignment.parent_id = tree.id
            ) SELECT id FROM tree""", (session_id, assignment_id)) as cursor:
            return [str(row["id"]) for row in await cursor.fetchall()]
