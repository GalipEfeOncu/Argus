"""Durable restart recovery; no remote mutation is ever replayed implicitly."""

from __future__ import annotations

from dataclasses import dataclass
import uuid

import aiosqlite

from app.db.database import transaction
from app.db.repositories import EventRepository, _now_ms, _safe_json
from app.services.assignment_scheduler import AssignmentScheduler


@dataclass(frozen=True)
class RecoveryReport:
    sessions: int
    orphaned_attempts: int
    unknown_tools: int
    unknown_provider_operations: int
    compacted_snapshots: int


class RecoveryService:
    """Rebuild projections and fence interrupted execution after a sidecar restart."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._events = EventRepository(db)

    async def recover_after_restart(self) -> RecoveryReport:
        async with self._db.execute("SELECT id FROM sessions WHERE status != 'setup' ORDER BY created_at_ms") as cursor:
            session_ids = [str(row["id"]) for row in await cursor.fetchall()]
        orphaned_attempts = unknown_tools = unknown_provider_operations = compacted = 0
        for session_id in session_ids:
            # The session table is a cache; immutable events remain the source
            # of truth even if the previous process stopped between writes.
            await self._events.rebuild_session_projection(session_id)
            await self._stop_wall_clock(session_id)
            unknown_tool_ids = await self._recover_tools(session_id)
            unknown_provider_ids, provider_operation_count = await self._recover_provider_operations(session_id)
            unknown_tools += len(unknown_tool_ids)
            unknown_provider_operations += provider_operation_count
            scheduler = AssignmentScheduler(self._db)
            recovered_attempts = await scheduler.recover_orphaned_attempts(
                session_id, blocked_assignment_ids=frozenset(unknown_tool_ids | unknown_provider_ids),
            )
            orphaned_attempts += len(recovered_attempts)
            compacted += await self._events.compact_snapshots(session_id)
        await self._forfeit_stale_reservations()
        return RecoveryReport(len(session_ids), orphaned_attempts, unknown_tools, unknown_provider_operations, compacted)

    async def _recover_tools(self, session_id: str) -> set[str]:
        """Mark lost tool responses failed; mutating effects are deliberately unknown."""

        async with transaction(self._db):
            async with self._db.execute(
                """SELECT id, assignment_id, operation_class, created_at_ms FROM tool_executions
                   WHERE session_id = ? AND exit_state IN ('requested', 'running')""", (session_id,)
            ) as cursor:
                rows = await cursor.fetchall()
            now = _now_ms()
            blocked_assignments: set[str] = set()
            for row in rows:
                tool_id = str(row["id"])
                mutation = row["operation_class"] == "mutating"
                summary = (
                    "The sidecar stopped while this mutating tool was running; its remote outcome is unknown and Argus will not replay it."
                    if mutation else "The sidecar stopped before this tool returned; it may be retried only through normal scheduler policy."
                )
                event = await self._events._append_in_transaction(
                    event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="tool.completed", actor_id="system",
                    payload={"toolExecutionId": tool_id, "assignmentId": str(row["assignment_id"]), "status": "failed",
                             "resultSummary": summary, "durationMs": max(0, now - int(row["created_at_ms"])), "artifactIds": []},
                    payload_json=_safe_json({"toolExecutionId": tool_id, "assignmentId": str(row["assignment_id"]), "status": "failed",
                             "resultSummary": summary, "durationMs": max(0, now - int(row["created_at_ms"])), "artifactIds": []}),
                    timestamp_ms=now, correlation_id=None, command_id=None,
                )
                await self._db.execute(
                    "UPDATE tool_executions SET exit_state = ?, result_summary = ?, completed_event_id = ?, updated_at_ms = ? WHERE id = ?",
                    ("outcome_unknown" if mutation else "orphaned", summary, event.event_id, now, tool_id),
                )
                if mutation and row["assignment_id"] is not None:
                    blocked_assignments.add(str(row["assignment_id"]))
            return blocked_assignments

    async def _recover_provider_operations(self, session_id: str) -> tuple[set[str], int]:
        async with transaction(self._db):
            async with self._db.execute(
                "SELECT assignment_id, mutation_class FROM provider_operations WHERE session_id = ? AND state IN ('pending', 'running')",
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()
            await self._db.execute(
                """UPDATE provider_operations SET state = 'outcome_unknown',
                   result_summary = 'The sidecar stopped before the provider outcome was recorded; Argus will not replay this operation.',
                   completed_at_ms = ? WHERE session_id = ? AND state IN ('pending', 'running')""",
                (_now_ms(), session_id),
            )
            return (
                {str(row["assignment_id"]) for row in rows if row["mutation_class"] == "mutating" and row["assignment_id"] is not None},
                len(rows),
            )

    async def _forfeit_stale_reservations(self) -> None:
        """No in-memory worker survived the restart, so held capacity cannot remain live."""

        from app.services.budget_counter_service import BudgetCounterService, CounterReservation
        async with transaction(self._db):
            async with self._db.execute("SELECT id, counter_kind, scope_id, amount FROM limit_reservations WHERE state = 'reserved'") as cursor:
                rows = await cursor.fetchall()
            budgets = BudgetCounterService(self._db)
            for row in rows:
                await budgets.release_prestart(CounterReservation(str(row["id"]), str(row["counter_kind"]), str(row["scope_id"]), float(row["amount"])))

    async def _stop_wall_clock(self, session_id: str) -> None:
        """Account only to the restart boundary; downtime is never runnable time."""

        now = _now_ms()
        async with transaction(self._db):
            await self._db.execute(
                """UPDATE session_runtime_clocks SET accumulated_running_ms = accumulated_running_ms +
                   CASE WHEN running_started_at_ms IS NULL THEN 0 ELSE MAX(0, ? - running_started_at_ms) END,
                   running_started_at_ms = NULL, updated_at_ms = ? WHERE session_id = ? AND running_started_at_ms IS NOT NULL""",
                (now, now, session_id),
            )
