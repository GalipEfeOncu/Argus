"""Provider-neutral reference execution for the first isolated coding task.

This deliberately small runner is used by the vertical acceptance scenario. It
exercises the same Coordinator, scheduler, grant, workspace, artifact, and
event-store boundaries that production workers use without depending on a
provider SDK or touching the original project.
"""

from __future__ import annotations

from pathlib import Path
import uuid

import aiosqlite

from app.db.repositories import EventRepository, _now_ms, _safe_json
from app.db.database import transaction
from app.providers.protocol import ProviderRequest, StructuredOutput
from app.providers.scripted import ScriptedProvider
from app.services.assignment_scheduler import AssignmentScheduler, ScheduledAssignment
from app.services.coordinator_cycle import CoordinatorCycle
from app.services.session_configuration_service import SessionConfigurationService
from app.services.worker_fence import session_mutation_fence
from app.services.workspace_service import ProjectWorkspaceService, ScopedToolService


class FirstVerticalTaskRunner:
    """Execute one fake Coordinator → Builder write against the session workspace."""

    def __init__(self, db: aiosqlite.Connection, *, managed_root: Path) -> None:
        self._db = db
        self._events = EventRepository(db)
        self._managed_root = managed_root

    async def request_scoped_write_grant(self, session_id: str) -> str | None:
        """Request a grant, returning an approval ID only when user input is needed.

        ``None`` means an existing policy grant authorizes the task immediately;
        an empty string means policy denied it and the denial is already visible.
        """

        from app.services.approval_grant_service import ApprovalGrantService
        async with transaction(self._db):
            # Acquire the write transaction before inspecting the status.  A
            # concurrent pause or cancellation must win instead of being
            # overwritten by our derived waiting/running transition.
            async with self._db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)) as cursor:
                session = await cursor.fetchone()
            if session is None or session["status"] not in {"preparing", "running"}:
                raise ValueError("The isolated task is no longer runnable.")
            authority = await ApprovalGrantService(self._db).request_in_transaction(
                session_id, capability="workspace.write", scope_path=".", assignment_id=None,
                operation_class="mutating", scope_summary="Write one generated file inside this session's isolated workspace.",
            )
            if authority.outcome == "ask":
                await self._events._append_in_transaction(
                    event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id,
                    event_type="session.status_changed", actor_id="system",
                    payload={"status": "waiting_approval", "reasonSummary": "Waiting for a scoped workspace write grant."},
                    payload_json=_safe_json({"status": "waiting_approval", "reasonSummary": "Waiting for a scoped workspace write grant."}),
                    timestamp_ms=_now_ms(), correlation_id=authority.grant_id, command_id=None,
                )
            elif authority.outcome == "allow" and session["status"] == "preparing":
                # A durable pre-authorization needs the same runnable-state
                # transition that a later human grant creates.  Without this,
                # the scheduler correctly refuses to dispatch while the
                # session remains in ``preparing``.
                payload = {
                    "status": "running",
                    "reasonSummary": "A session-scoped pre-authorization allows the isolated Builder task.",
                }
                await self._events._append_in_transaction(
                    event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id,
                    event_type="session.status_changed", actor_id="system",
                    payload=payload, payload_json=_safe_json(payload),
                    timestamp_ms=_now_ms(), correlation_id=authority.grant_id, command_id=None,
                )
            elif authority.outcome == "deny":
                payload = {"errorId": f"permission_{uuid.uuid4().hex}", "code": "permission_denied", "summary": authority.reason, "recoverable": True}
                await self._events._append_in_transaction(
                    event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="error.created", actor_id="system",
                    payload=payload, payload_json=_safe_json(payload),
                    timestamp_ms=_now_ms(), correlation_id=None, command_id=None,
                )
        if authority.outcome == "ask":
            return authority.grant_id or ""
        if authority.outcome == "allow":
            return None
        return ""

    async def run_after_grant(self, session_id: str) -> str:
        """Route to Builder, write one file, produce a diff artifact, and complete."""

        if not await self._has_scoped_write_grant(session_id):
            raise ValueError("The isolated Builder task requires an active scoped workspace.write grant.")
        snapshot = await SessionConfigurationService(self._db).current(session_id)
        builder = next(
            (agent for agent in snapshot.agent_snapshots
             if agent["id"] in snapshot.available_agent_ids and agent["role"] == "builder"),
            None,
        )
        if builder is None:
            raise ValueError("The vertical task requires an available Builder.")
        action = {
            "type": "assignments",
            "routingSummary": "The Coordinator assigned the isolated change to the available Builder.",
            "assignments": [{
                "proposalId": f"proposal_{uuid.uuid4().hex}", "assigneeAgentId": builder["id"],
                "objective": "Create one reviewable file in the isolated workspace.",
                "acceptanceCriteria": ["Write the requested file", "Record a reviewable diff artifact"],
                "operationClass": "mutating", "requestedBudget": {},
                "requestedCapabilities": ["workspace.write"],
                "reasonSummary": "The Builder has the approved workspace write capability.",
            }],
        }
        result = await CoordinatorCycle(self._db).execute(
            session_id, ScriptedProvider(((StructuredOutput(action),),)),
            ProviderRequest(f"vertical_coordinator_{uuid.uuid4().hex}", "fake-provider", (
                {"role": "user", "content": "Complete the isolated reference change."},
            )),
        )
        if result.action is None:
            raise RuntimeError(result.error_summary or "Coordinator did not create the Builder assignment.")
        scheduled = await self._running_builder_attempt(session_id)
        return await self._write_and_complete(session_id, scheduled)

    async def _running_builder_attempt(self, session_id: str) -> ScheduledAssignment:
        async with self._db.execute(
            """SELECT assignment.id AS assignment_id, proposal.id AS proposal_id, attempt.id AS attempt_id,
                      assignment.operation_class, assignment.writer_lease_id
               FROM assignments assignment
               JOIN assignment_proposals proposal ON proposal.assignment_id = assignment.id
               JOIN assignment_attempts attempt ON attempt.assignment_id = assignment.id
               WHERE assignment.session_id = ? AND assignment.operation_class = 'mutating'
                 AND assignment.state = 'running' AND attempt.state = 'running'
               ORDER BY attempt.started_at_ms DESC LIMIT 1""",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("Builder assignment did not become runnable after the scoped grant.")
        return ScheduledAssignment(
            str(row["assignment_id"]), str(row["proposal_id"]), str(row["attempt_id"]),
            str(row["operation_class"]), None if row["writer_lease_id"] is None else str(row["writer_lease_id"]),
        )

    async def _write_and_complete(self, session_id: str, scheduled: ScheduledAssignment) -> str:
        scheduler = AssignmentScheduler(self._db)
        from app.services.budget_counter_service import BudgetCounterService
        budgets = BudgetCounterService(self._db)
        # Reserve both the tool and the resulting revision before requesting a
        # mutating operation.  A hard limit therefore prevents the write rather
        # than merely reporting it after the workspace changed.
        tool_reservation = None
        revision_reservation = None
        rejected = None
        tool_id = f"tool_{uuid.uuid4().hex}"
        async with transaction(self._db):
            try:
                from app.services.approval_grant_service import ApprovalGrantService
                authority = await ApprovalGrantService(self._db).evaluate(
                    session_id, capability="workspace.write", scope_path=".", operation_class="mutating", consume_once=True,
                )
                if authority.outcome != "allow":
                    raise PermissionError("The scoped workspace.write grant is no longer active.")
                tool_reservation = await budgets.reserve_in_transaction(
                    session_id, counter="tool_calls", scope_type="assignment", scope_id=scheduled.assignment_id,
                    assignment_id=scheduled.assignment_id, hold=True,
                )
                revision_reservation = await budgets.reserve_in_transaction(
                    session_id, counter="revisions", scope_type="finding", scope_id=session_id, hold=True,
                )
                requested_payload = {
                    "toolExecutionId": tool_id, "assignmentId": scheduled.assignment_id, "toolName": "write_file",
                    "operationClass": "mutating", "requestSummary": "Write one generated file inside the isolated workspace.",
                }
                await self._events._append_in_transaction(
                    event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="tool.requested", actor_id="builder",
                    payload=requested_payload, payload_json=_safe_json(requested_payload), timestamp_ms=_now_ms(),
                    correlation_id=scheduled.attempt_id, command_id=None,
                )
            except Exception as error:
                if tool_reservation is not None:
                    await budgets.release_prestart(tool_reservation)
                rejected = error
        if rejected is not None:
            from app.services.budget_counter_service import BudgetExceeded
            if isinstance(rejected, BudgetExceeded):
                from app.services.limit_resolution_service import LimitResolutionService
                async with transaction(self._db):
                    await LimitResolutionService(self._db).request_latest_in_transaction(
                        session_id, counter=rejected.counter, scope_id=rejected.scope_id, assignment_id=scheduled.assignment_id,
                    )
            raise rejected
        assert tool_reservation is not None and revision_reservation is not None
        async with transaction(self._db):
            await budgets.consume_reservation(tool_reservation)
            await budgets.consume_reservation(revision_reservation)
        await self._events.append(
            event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="tool.started", actor_id="builder",
            payload={"toolExecutionId": tool_id, "assignmentId": scheduled.assignment_id, "toolName": "write_file"},
            timestamp_ms=_now_ms(), correlation_id=scheduled.attempt_id,
        )
        relative_path = "argus-vertical-task.txt"
        content = "This reviewable change was written only in the Argus session workspace.\n"
        async with session_mutation_fence.mutation(session_id):
            # The command processor waits on the same fence before committing
            # cancellation, so no accepted cancellation can be followed by a
            # workspace write from this task.
            await scheduler.checkpoint(scheduled.attempt_id, {"phase": "before_fake_write"})
            workspace_service = ProjectWorkspaceService(self._db, managed_root=self._managed_root)
            workspace = await workspace_service.workspace_for_session(session_id)
            ScopedToolService(workspace).write_text(relative_path, content)
            revision = await workspace_service.record_mutation(session_id)
            async with self._db.execute(
                "SELECT id FROM artifacts WHERE session_id = ? AND kind = 'diff' AND checksum = ? ORDER BY created_at_ms DESC LIMIT 1",
                (session_id, revision),
            ) as cursor:
                artifact = await cursor.fetchone()
            if artifact is None:
                raise RuntimeError("Workspace mutation did not create a diff artifact.")
            artifact_id = str(artifact["id"])
            await scheduler.checkpoint(scheduled.attempt_id, {"phase": "after_fake_write", "revision": revision})
        await self._events.append(
            event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="tool.completed", actor_id="builder",
            payload={"toolExecutionId": tool_id, "assignmentId": scheduled.assignment_id, "status": "succeeded",
                     "resultSummary": "Wrote the isolated reference file.", "durationMs": 0, "artifactIds": [artifact_id]},
            timestamp_ms=_now_ms(), correlation_id=scheduled.attempt_id,
        )
        await self._events.append(
            event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="artifact.diff_updated", actor_id="builder",
            payload={"artifactId": artifact_id, "assignmentId": scheduled.assignment_id, "filePath": relative_path,
                     "additions": 1, "deletions": 0, "byteLength": len(content.encode()), "truncated": False},
            timestamp_ms=_now_ms(), correlation_id=scheduled.attempt_id,
        )
        await scheduler.complete_attempt(
            session_id, scheduled.attempt_id, output_summary="Builder completed the isolated reference change.",
            evidence=[{"kind": "implementation_summary", "summary": "One isolated file and diff artifact were produced.", "artifactIds": [artifact_id]}],
        )
        from app.services.gate_engine import GateEngine
        gates = GateEngine(self._db)
        if any(state.status == "pending" for state in await gates.states(session_id)):
            await gates.route_unsatisfied(session_id)
            await gates.append_states(session_id)
            await scheduler.dispatch_ready(session_id)
            return artifact_id
        await self._events.append(
            event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="session.status_changed", actor_id="system",
            payload={"status": "completed", "reasonSummary": "The isolated reference task completed with a reviewable diff."},
            timestamp_ms=_now_ms(), correlation_id=scheduled.attempt_id,
        )
        return artifact_id

    async def _has_scoped_write_grant(self, session_id: str) -> bool:
        from app.services.approval_grant_service import ApprovalGrantService
        decision = await ApprovalGrantService(self._db).evaluate(
            session_id, capability="workspace.write", scope_path=".", operation_class="mutating", consume_once=False,
        )
        return decision.outcome == "allow"
