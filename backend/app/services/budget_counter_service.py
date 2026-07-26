"""Durable, transactional accounting for user-configured execution limits.

The service deliberately owns only user-configured counters.  Writer leases,
database timeouts, and other runtime safety guards stay independent so changing
a user budget can never weaken an internal resource guard.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal
import uuid

import aiosqlite

from app.db.database import transaction
from app.db.repositories import EventRepository, _now_ms, _safe_json
from app.services.session_configuration_service import SessionConfigurationService


CounterKind = Literal[
    "revisions", "assignment_attempts", "model_iterations", "tool_calls",
    "wall_clock_seconds", "tokens", "cost", "parallel_read_only_assignments",
]

_LIMIT_FIELDS: dict[str, str] = {
    "revisions": "maxRevisionsPerFinding",
    "assignment_attempts": "maxAssignmentAttempts",
    "model_iterations": "maxModelIterationsPerAssignment",
    "tool_calls": "maxToolCallsPerAssignment",
    "wall_clock_seconds": "maxWallClockSeconds",
    "tokens": "maxSessionTokens",
    "cost": "maxSessionCost",
    "parallel_read_only_assignments": "maxParallelReadOnlyAssignments",
}


class BudgetExceeded(ValueError):
    """Raised after a durable hard-limit event prevents excess work."""

    def __init__(self, counter: str, scope_id: str) -> None:
        super().__init__(f"{counter} limit reached for {scope_id}")
        self.counter = counter
        self.scope_id = scope_id


@dataclass(frozen=True)
class CounterReservation:
    id: str
    counter: str
    scope_id: str
    amount: float


class BudgetCounterService:
    """Reserve, consume, correct, and expose all configured limit counters."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._events = EventRepository(db)

    async def reserve(
        self, session_id: str, *, counter: CounterKind, scope_type: str, scope_id: str,
        amount: float = 1, assignment_id: str | None = None, hold: bool = False,
    ) -> CounterReservation:
        """Reserve an externally requested unit in one durable transaction."""

        rejected: BudgetExceeded | None = None
        reservation: CounterReservation | None = None
        async with transaction(self._db):
            try:
                reservation = await self.reserve_in_transaction(
                    session_id, counter=counter, scope_type=scope_type, scope_id=scope_id,
                    amount=amount, assignment_id=assignment_id, hold=hold,
                )
            except BudgetExceeded as error:
                # Commit the limit event before returning the rejection.
                rejected = error
        if rejected is not None:
            raise rejected
        assert reservation is not None
        return reservation

    async def reserve_in_transaction(
        self, session_id: str, *, counter: CounterKind, scope_type: str, scope_id: str,
        amount: float = 1, assignment_id: str | None = None, hold: bool = False,
    ) -> CounterReservation:
        """Reserve work before it starts; caller must already own a transaction."""

        if amount < 0:
            raise ValueError("counter reservation amount must be non-negative")
        await self._check_wall_clock(session_id)
        snapshot = await SessionConfigurationService(self._db).current(session_id)
        ceiling = snapshot.execution_limits.get(_LIMIT_FIELDS[counter])
        row = await self._counter_row(session_id, counter, scope_type, scope_id)
        current = 0.0 if row is None else float(row["consumed_real"])
        next_value = current + amount
        threshold = None if ceiling is None else float(ceiling)
        if threshold is not None and next_value > threshold:
            await self._append_limit_event(session_id, "limit.reached", counter, scope_id, current, threshold, True, snapshot)
            raise BudgetExceeded(counter, scope_id)
        warning = threshold is not None and next_value >= threshold * float(snapshot.execution_limits["softWarningRatio"])
        warning_emitted = bool(row["warning_emitted"]) if row is not None else False
        reservation_id = f"reserve_{uuid.uuid4().hex}"
        now = _now_ms()
        if row is None:
            await self._db.execute(
                """INSERT INTO limit_counters (id, session_id, scope_type, scope_id, counter_kind, consumed_value,
                   threshold_value, consumed_real, threshold_real, warning_emitted, updated_at_ms)
                   VALUES (?, ?, ?, ?, ?, 0, ?, 0, ?, 0, ?)""",
                (f"counter_{uuid.uuid4().hex}", session_id, scope_type, scope_id, counter, ceiling, threshold, now),
            )
        await self._db.execute(
            """INSERT INTO limit_reservations (id, session_id, assignment_id, counter_kind, scope_type, scope_id,
               amount, state, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (reservation_id, session_id, assignment_id, counter, scope_type, scope_id, amount,
             "reserved" if hold else "consumed", now),
        )
        # A held reservation still occupies capacity immediately, so concurrent
        # dispatches cannot both observe the same free read-only slot.
        await self._set_counter(session_id, counter, scope_type, scope_id, next_value, threshold, warning_emitted or warning)
        if warning and not warning_emitted:
            await self._append_limit_event(session_id, "limit.warning", counter, scope_id, next_value, threshold, False, snapshot)
        return CounterReservation(reservation_id, counter, scope_id, amount)

    async def consume_reservation(self, reservation: CounterReservation) -> None:
        """Commit held capacity at work start; non-capacity work is never refunded."""

        async with self._db.execute("SELECT * FROM limit_reservations WHERE id = ?", (reservation.id,)) as cursor:
            row = await cursor.fetchone()
        if row is None or row["state"] != "reserved":
            raise ValueError("reservation is no longer available")
        await self._db.execute("UPDATE limit_reservations SET state = 'consumed', finalized_at_ms = ? WHERE id = ?", (_now_ms(), reservation.id))

    async def release_capacity(self, reservation_id: str) -> None:
        """Release a completed read-only slot; it is a live guard, not spent work."""

        async with self._db.execute("SELECT * FROM limit_reservations WHERE id = ?", (reservation_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None or row["state"] not in {"reserved", "consumed"}:
            return
        existing = await self._counter_row(str(row["session_id"]), str(row["counter_kind"]), str(row["scope_type"]), str(row["scope_id"]))
        if existing is not None:
            value = max(0.0, float(existing["consumed_real"]) - float(row["amount"]))
            await self._set_counter(str(row["session_id"]), str(row["counter_kind"]), str(row["scope_type"]), str(row["scope_id"]), value, existing["threshold_real"], await self._warning_still_active(str(row["session_id"]), value, existing["threshold_real"], bool(existing["warning_emitted"])))
        await self._db.execute("UPDATE limit_reservations SET state = 'released', finalized_at_ms = ? WHERE id = ?", (_now_ms(), reservation_id))

    async def release_assignment_capacity(self, assignment_id: str) -> None:
        """Release all live read-only capacity held by one terminal assignment."""

        async with self._db.execute(
            "SELECT id FROM limit_reservations WHERE assignment_id = ? AND counter_kind = 'parallel_read_only_assignments' AND state IN ('reserved', 'consumed')",
            (assignment_id,),
        ) as cursor:
            reservation_ids = [str(row["id"]) for row in await cursor.fetchall()]
        for reservation_id in reservation_ids:
            await self.release_capacity(reservation_id)

    async def release_prestart(self, reservation: CounterReservation) -> None:
        """Return only a reservation that demonstrably never reached started work."""

        async with self._db.execute("SELECT * FROM limit_reservations WHERE id = ? AND state = 'reserved'", (reservation.id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return
        existing = await self._counter_row(str(row["session_id"]), str(row["counter_kind"]), str(row["scope_type"]), str(row["scope_id"]))
        if existing is not None:
            value = max(0.0, float(existing["consumed_real"]) - float(row["amount"]))
            await self._set_counter(str(row["session_id"]), str(row["counter_kind"]), str(row["scope_type"]), str(row["scope_id"]), value, existing["threshold_real"], await self._warning_still_active(str(row["session_id"]), value, existing["threshold_real"], bool(existing["warning_emitted"])))
        await self._db.execute(
            "UPDATE limit_reservations SET state = 'released', finalized_at_ms = ? WHERE id = ? AND state = 'reserved'",
            (_now_ms(), reservation.id),
        )

    async def record_provider_usage(
        self, session_id: str, assignment_id: str, *, input_tokens: int, output_tokens: int,
        normalized_cost: float | None, duration_ms: int, cost_uncertainty: Literal["exact", "estimated", "unavailable"],
    ) -> None:
        """Correct durable provider usage by delta and publish normalized uncertainty."""

        if min(input_tokens, output_tokens, duration_ms) < 0 or normalized_cost is not None and normalized_cost < 0:
            raise ValueError("usage values must be non-negative")
        rejected: BudgetExceeded | None = None
        async with transaction(self._db):
            try:
                await self._record_provider_usage_in_transaction(
                    session_id, assignment_id, input_tokens=input_tokens, output_tokens=output_tokens,
                    normalized_cost=normalized_cost, duration_ms=duration_ms, cost_uncertainty=cost_uncertainty,
                )
            except BudgetExceeded as error:
                rejected = error
        if rejected is not None:
            raise rejected

    async def record_coordinator_usage(
        self, session_id: str, *, input_tokens: int, output_tokens: int, normalized_cost: float | None,
        duration_ms: int, cost_uncertainty: Literal["exact", "estimated", "unavailable"],
    ) -> None:
        """Record provider usage that belongs to the mandatory Coordinator."""

        if min(input_tokens, output_tokens, duration_ms) < 0 or normalized_cost is not None and normalized_cost < 0:
            raise ValueError("usage values must be non-negative")
        rejected: BudgetExceeded | None = None
        async with transaction(self._db):
            try:
                await self._adjust(session_id, "tokens", "session", session_id, input_tokens + output_tokens)
                if normalized_cost is not None:
                    await self._adjust(session_id, "cost", "session", session_id, normalized_cost)
                payload = {"scopeId": session_id, "inputTokens": input_tokens, "outputTokens": output_tokens,
                           "normalizedCost": normalized_cost, "durationMs": duration_ms, "costUncertainty": cost_uncertainty}
                await self._events._append_in_transaction(
                    event_id=f"usage_{uuid.uuid4().hex}", session_id=session_id, event_type="usage.updated", actor_id="system",
                    payload=payload, payload_json=_safe_json(payload), timestamp_ms=_now_ms(), correlation_id=None, command_id=None,
                )
            except BudgetExceeded as error:
                rejected = error
        if rejected is not None:
            raise rejected

    async def _record_provider_usage_in_transaction(
        self, session_id: str, assignment_id: str, *, input_tokens: int, output_tokens: int,
        normalized_cost: float | None, duration_ms: int, cost_uncertainty: Literal["exact", "estimated", "unavailable"],
    ) -> None:
        async with self._db.execute(
            """SELECT attempt.id, attempt.usage_json FROM assignment_attempts attempt
               JOIN assignments assignment ON assignment.id = attempt.assignment_id
               WHERE attempt.assignment_id = ? AND assignment.session_id = ?
               ORDER BY attempt.attempt_number DESC LIMIT 1""", (assignment_id, session_id)
        ) as cursor:
            attempt = await cursor.fetchone()
        if attempt is None:
            raise ValueError("assignment has no attempt")
        previous = json.loads(attempt["usage_json"])
        tokens = input_tokens + output_tokens
        previous_tokens = int(previous.get("inputTokens", 0)) + int(previous.get("outputTokens", 0))
        await self._adjust(session_id, "tokens", "session", session_id, tokens - previous_tokens)
        if normalized_cost is not None:
            await self._adjust(session_id, "cost", "session", session_id, normalized_cost - float(previous.get("normalizedCost") or 0))
        usage = {"inputTokens": input_tokens, "outputTokens": output_tokens, "normalizedCost": normalized_cost,
                 "durationMs": duration_ms, "costUncertainty": cost_uncertainty}
        await self._db.execute("UPDATE assignment_attempts SET usage_json = ?, updated_at_ms = ? WHERE id = ?", (_safe_json(usage), _now_ms(), attempt["id"]))
        payload = {"scopeId": assignment_id, **usage}
        await self._events._append_in_transaction(
            event_id=f"usage_{uuid.uuid4().hex}", session_id=session_id, event_type="usage.updated", actor_id="system",
            payload=payload, payload_json=_safe_json(payload), timestamp_ms=_now_ms(), correlation_id=assignment_id, command_id=None,
        )

    async def record_tool_call(self, session_id: str, assignment_id: str) -> None:
        await self.reserve(session_id, counter="tool_calls", scope_type="assignment", scope_id=assignment_id, assignment_id=assignment_id)

    async def record_model_iteration(self, session_id: str, assignment_id: str) -> None:
        await self.reserve(session_id, counter="model_iterations", scope_type="assignment", scope_id=assignment_id, assignment_id=assignment_id)

    async def record_revision(self, session_id: str, finding_id: str | None = None) -> None:
        scope_id = finding_id or session_id
        await self.reserve(session_id, counter="revisions", scope_type="finding", scope_id=scope_id)

    async def _adjust(self, session_id: str, counter: CounterKind, scope_type: str, scope_id: str, delta: float) -> None:
        row = await self._counter_row(session_id, counter, scope_type, scope_id)
        current = 0.0 if row is None else float(row["consumed_real"])
        if delta > 0:
            await self.reserve_in_transaction(session_id, counter=counter, scope_type=scope_type, scope_id=scope_id, amount=delta)
        elif row is not None:
            await self._set_counter(session_id, counter, scope_type, scope_id, max(0, current + delta), row["threshold_real"], bool(row["warning_emitted"]))

    async def _check_wall_clock(self, session_id: str) -> None:
        snapshot = await SessionConfigurationService(self._db).current(session_id)
        ceiling = snapshot.execution_limits.get("maxWallClockSeconds")
        if ceiling is None:
            return
        async with self._db.execute("SELECT accumulated_running_ms, running_started_at_ms FROM session_runtime_clocks WHERE session_id = ?", (session_id,)) as cursor:
            clock = await cursor.fetchone()
        now = _now_ms()
        elapsed_ms = 0 if clock is None else int(clock["accumulated_running_ms"]) + (0 if clock["running_started_at_ms"] is None else now - int(clock["running_started_at_ms"]))
        elapsed = elapsed_ms / 1000
        if elapsed > float(ceiling):
            await self._append_limit_event(session_id, "limit.reached", "wall_clock_seconds", session_id, elapsed, float(ceiling), True, snapshot)
            raise BudgetExceeded("wall_clock_seconds", session_id)
        if elapsed >= float(ceiling) * float(snapshot.execution_limits["softWarningRatio"]):
            row = await self._counter_row(session_id, "wall_clock_seconds", "session", session_id)
            if row is None or not bool(row["warning_emitted"]):
                await self._set_counter(session_id, "wall_clock_seconds", "session", session_id, elapsed, float(ceiling), True)
                await self._append_limit_event(session_id, "limit.warning", "wall_clock_seconds", session_id, elapsed, float(ceiling), False, snapshot)

    async def _counter_row(self, session_id: str, counter: str, scope_type: str, scope_id: str) -> aiosqlite.Row | None:
        async with self._db.execute("SELECT * FROM limit_counters WHERE session_id = ? AND counter_kind = ? AND scope_type = ? AND scope_id = ?", (session_id, counter, scope_type, scope_id)) as cursor:
            return await cursor.fetchone()

    async def _set_counter(self, session_id: str, counter: str, scope_type: str, scope_id: str, value: float, threshold: float | None, warning_emitted: bool) -> None:
        now = _now_ms()
        await self._db.execute(
            """UPDATE limit_counters SET consumed_value = ?, consumed_real = ?, threshold_value = ?, threshold_real = ?,
               warning_emitted = ?, updated_at_ms = ? WHERE session_id = ? AND counter_kind = ? AND scope_type = ? AND scope_id = ?""",
            (int(value), value, threshold, threshold, int(warning_emitted), now, session_id, counter, scope_type, scope_id),
        )

    async def _warning_still_active(self, session_id: str, value: float, threshold: float | None, warning_emitted: bool) -> bool:
        if not warning_emitted or threshold is None:
            return warning_emitted
        snapshot = await SessionConfigurationService(self._db).current(session_id)
        return value >= threshold * float(snapshot.execution_limits["softWarningRatio"])

    async def _append_limit_event(self, session_id: str, event_type: str, counter: str, scope_id: str, current: float, threshold: float, hard: bool, snapshot) -> None:
        payload = {"counter": counter, "scopeId": scope_id, "current": current, "threshold": threshold,
                   "hard": hard, "resolution": snapshot.approval_policy["limitResolution"]}
        await self._events._append_in_transaction(
            event_id=f"limit_{uuid.uuid4().hex}", session_id=session_id, event_type=event_type, actor_id="system",
            payload=payload, payload_json=_safe_json(payload), timestamp_ms=_now_ms(), correlation_id=None, command_id=None,
        )
