"""Durable, idempotent processing for canonical shared-room commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import uuid

import aiosqlite

from app.db.database import transaction
from app.db.repositories import EventRepository, StoredEvent, _now_ms, _safe_json
from app.schemas.session_commands import ArgusSessionCommand
from app.services.session_configuration_service import ConfigurationError, SessionConfigurationService
from app.services.participant_instruction_service import ParticipantInstructionService


class CommandRejected(ValueError):
    """A valid command that is not legal for the current deterministic state."""


LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"preparing", "cancelled", "failed"}),
    "preparing": frozenset({"running", "cancelled", "failed"}),
    "running": frozenset({
        "paused", "waiting_approval", "waiting_decision", "completed",
        "completed_partial", "cancelled", "failed",
    }),
    "paused": frozenset({"running", "cancelled", "failed"}),
    "waiting_approval": frozenset({"running", "paused", "cancelled", "failed"}),
    "waiting_decision": frozenset({"running", "paused", "completed_partial", "cancelled", "failed"}),
    "completed": frozenset(),
    "completed_partial": frozenset(),
    "cancelled": frozenset(),
    "failed": frozenset(),
}


@dataclass(frozen=True)
class CommandOutcome:
    events: tuple[StoredEvent, ...]
    duplicate: bool


class CommandProcessor:
    """Accept each command at most once, committing its visible result before return."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._events = EventRepository(db)

    async def process(self, session_id: str, command: ArgusSessionCommand) -> CommandOutcome:
        """Persist the accepted outcome atomically; duplicates return the original event."""

        supersede_coordinator = False
        if command.type in {"session.cancel", "participant.interrupt"}:
            # A cancellation is committed only after an already-authorized
            # workspace mutation leaves its short critical section.  This
            # closes the check-to-write gap for the live worker runtime.
            from app.services.worker_fence import session_mutation_fence
            await session_mutation_fence.wait_for_mutations(session_id)
        async with transaction(self._db):
            duplicate = await self._events.events_for_command(session_id, command.command_id)
            if duplicate:
                return CommandOutcome(duplicate, True)

            status = await self._current_status(session_id)
            if command.type == "decision.resolve" and command.payload.choice == "deliver_partial":
                await self._require_partial_acceptance(session_id, command.payload.decision_id)
            if command.type == "session.configuration.update":
                specs, interrupted_assignments = await self._configuration_outcome_specs(session_id, command)
            else:
                specs = self._outcome_specs(session_id, command, status)
                interrupted_assignments = ()
            persisted: list[StoredEvent] = []
            for index, (event_type, actor_id, payload) in enumerate(specs):
                event = await self._events._append_in_transaction(
                    event_id=str(uuid.uuid4()), session_id=session_id, event_type=event_type,
                    actor_id=actor_id, payload=payload, payload_json=_safe_json(payload),
                    timestamp_ms=_now_ms(), correlation_id=command.command_id if index == 0 else None,
                    command_id=command.command_id if index == 0 else None,
                )
                persisted.append(event)
            if command.type == "message.send":
                try:
                    instructions = await ParticipantInstructionService(self._db).record_message(
                        session_id, persisted[0].event_id, command.payload.mention_ids,
                    )
                except ConfigurationError as error:
                    raise CommandRejected(error.code) from error
                supersede_coordinator = any(instruction.delivery_kind == "coordinator" for instruction in instructions)
            if command.type == "approval.resolve" and command.payload.resolution == "grant":
                now = _now_ms()
                for capability in command.payload.grant_capabilities:
                    await self._db.execute(
                        """INSERT INTO approvals (id, session_id, capability, scope_json, decision, resolver_id,
                           requested_at_ms, resolved_at_ms, request_event_id, resolution_event_id)
                           VALUES (?, ?, ?, ?, 'granted', 'human', ?, ?, ?, ?)""",
                        (f"grant_{command.command_id}_{capability}", session_id, capability,
                         _safe_json({"summary": command.payload.scope_summary}), now, now,
                         persisted[0].event_id, persisted[0].event_id),
                    )
            if command.type == "session.cancel":
                persisted.extend(await self._cancel_assignments_in_transaction(
                    session_id, reason=command.payload.reason_summary or "Cancelled by the user.",
                ))
            elif command.type == "participant.interrupt":
                persisted.extend(await self._cancel_assignments_in_transaction(
                    session_id, participant_id=command.payload.participant_id, reason=command.payload.reason_summary,
                ))
            if interrupted_assignments:
                await self._db.executemany(
                    "UPDATE assignments SET state = 'interrupted', updated_at_ms = ? WHERE id = ? AND session_id = ?",
                    [(_now_ms(), assignment_id, session_id) for assignment_id in interrupted_assignments],
                )
            await self._db.execute(
                """INSERT INTO command_receipts
                   (session_id, command_id, command_type, command_json, outcome_event_id,
                    outcome_event_ids_json, accepted_at_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, command.command_id, command.type,
                    _safe_json(command.model_dump(by_alias=True)), persisted[0].event_id,
                    _safe_json([event.event_id for event in persisted]), _now_ms(),
                ),
            )
            outcome = CommandOutcome(tuple(persisted), False)
        if supersede_coordinator:
            # Never cancel a worker before the instruction that supersedes it
            # has committed. External provider I/O is deliberately outside the
            # SQLite transaction boundary.
            from app.services.coordinator_cycle import CoordinatorCycle
            await CoordinatorCycle.supersede_active(session_id)
        return outcome

    async def _cancel_assignments_in_transaction(
        self, session_id: str, *, reason: str, participant_id: str | None = None,
    ) -> list[StoredEvent]:
        """Persist cancellation, attempt fencing, and lease release with its command."""

        query = "SELECT * FROM assignments WHERE session_id = ? AND state IN ('created', 'running')"
        parameters: list[str] = [session_id]
        if participant_id is not None:
            query = """WITH RECURSIVE tree(id) AS (
                SELECT id FROM assignments WHERE session_id = ? AND assignee_session_agent_id = ?
                  AND state IN ('created', 'running')
                UNION ALL
                SELECT child.id FROM assignments child JOIN tree ON child.parent_id = tree.id
                  WHERE child.session_id = ? AND child.state IN ('created', 'running')
            ) SELECT assignment.* FROM assignments assignment JOIN tree ON tree.id = assignment.id"""
            parameters = [session_id, participant_id, session_id]
        query += " ORDER BY created_at_ms, rowid"
        async with self._db.execute(query, tuple(parameters)) as cursor:
            assignments = await cursor.fetchall()
        cancelled: list[StoredEvent] = []
        for assignment in assignments:
            now = _now_ms()
            payload = {"assignmentId": assignment["id"], "reasonSummary": reason}
            event = await self._events._append_in_transaction(
                event_id=str(uuid.uuid4()), session_id=session_id, event_type="assignment.cancelled", actor_id="system",
                payload=payload, payload_json=_safe_json(payload), timestamp_ms=now, correlation_id=None, command_id=None,
            )
            await self._db.execute("UPDATE assignments SET state = 'cancelled', terminal_event_id = ?, updated_at_ms = ? WHERE id = ?", (event.event_id, now, assignment["id"]))
            await self._db.execute("UPDATE assignment_attempts SET state = 'cancelled', completed_at_ms = ?, updated_at_ms = ? WHERE assignment_id = ? AND state = 'running'", (now, now, assignment["id"]))
            if assignment["writer_lease_id"] is not None:
                async with self._db.execute("SELECT project_id, session_id FROM writer_leases WHERE id = ? AND released_at_ms IS NULL", (assignment["writer_lease_id"],)) as cursor:
                    lease = await cursor.fetchone()
                if lease is not None:
                    await self._db.execute("UPDATE writer_leases SET released_at_ms = ?, release_reason = 'cancelled' WHERE id = ?", (now, assignment["writer_lease_id"]))
                    await self._db.execute("UPDATE projects SET lock_session_id = NULL, lock_acquired_at_ms = NULL, updated_at_ms = ? WHERE id = ? AND lock_session_id = ?", (now, lease["project_id"], lease["session_id"]))
            cancelled.append(event)
        return cancelled

    async def _current_status(self, session_id: str) -> str:
        async with self._db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise CommandRejected("session_not_found")
        # Transitional sessions are readable, but their first canonical command
        # starts from the canonical lifecycle's created state.
        return "created" if row["status"] == "setup" else str(row["status"])

    async def _require_partial_acceptance(self, session_id: str, decision_id: str) -> None:
        """Only a persisted partial-outcome request can become completed_partial."""

        async with self._db.execute(
            """SELECT 1 FROM events requested WHERE requested.session_id = ?
               AND requested.event_type = 'decision.requested'
               AND json_extract(requested.payload_json, '$.decisionId') = ?
               AND json_extract(requested.payload_json, '$.purpose') = 'partial_completion'
               AND NOT EXISTS (
                 SELECT 1 FROM events recorded WHERE recorded.session_id = requested.session_id
                   AND recorded.event_type = 'decision.recorded'
                   AND json_extract(recorded.payload_json, '$.decisionId') = ?
               ) LIMIT 1""",
            (session_id, decision_id, decision_id),
        ) as cursor:
            if await cursor.fetchone() is None:
                raise CommandRejected("partial_acceptance_not_requested")

    @staticmethod
    def _require_transition(current: str, target: str) -> None:
        if target not in LIFECYCLE_TRANSITIONS.get(current, frozenset()):
            raise CommandRejected(f"illegal_transition:{current}->{target}")

    def _outcome_specs(
        self, session_id: str, command: ArgusSessionCommand, status: str,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        payload = command.payload
        if command.type == "message.send":
            return [("message.created", "human", {
                "messageId": f"msg_{command.command_id}", "authorId": "human",
                "authorKind": "human", "content": payload.content, "mentionIds": payload.mention_ids,
                "streaming": False,
            })]
        if command.type == "session.start":
            return [self._status_spec(status, "preparing", "Session preparation started.")]
        if command.type == "session.pause":
            return [self._status_spec(status, "paused", "Paused by the user.")]
        if command.type == "session.resume":
            return [self._status_spec(status, "running", "Resumed by the user.")]
        if command.type == "session.cancel":
            return [self._status_spec(status, "cancelled", payload.reason_summary or "Cancelled by the user.")]
        if command.type == "participant.interrupt":
            return [("participant.status_changed", "human", {
                "participantId": payload.participant_id, "participantKind": "agent", "status": "stopped",
                "actionSummary": payload.reason_summary,
            })]
        if command.type == "approval.resolve":
            self._require_transition(status, "running")
            resolution = {"approve": "approved", "reject": "rejected", "grant": "granted"}[payload.resolution]
            approval: dict[str, Any] = {"approvalId": payload.approval_id, "resolution": resolution}
            if payload.resolution == "grant":
                approval["grantId"] = f"grant_{command.command_id}"
                approval["reasonSummary"] = payload.scope_summary
            return [
                ("approval.resolved", "human", approval),
                ("session.status_changed", "system", {"status": "running", "reasonSummary": "Approval resolved."}),
            ]
        if command.type == "decision.resolve":
            target = "completed_partial" if payload.choice == "deliver_partial" else (
                "cancelled" if payload.choice == "stop" else "running"
            )
            self._require_transition(status, target)
            return [
                ("decision.recorded", "human", {
                    "decisionId": payload.decision_id, "choice": payload.choice,
                    "reasonSummary": payload.reason_summary or "Decision recorded.",
                }),
                ("session.status_changed", "system", {"status": target, "reasonSummary": "Decision applied."}),
            ]
        raise CommandRejected(f"unsupported_command:{command.type}")

    async def _configuration_outcome_specs(
        self, session_id: str, command: ArgusSessionCommand,
    ) -> tuple[list[tuple[str, str, dict[str, Any]]], tuple[str, ...]]:
        """Preview authority reductions before committing an immutable version."""

        # The union is narrowed by process(), but retain a defensive guard so
        # future callers cannot bypass the discriminated command contract.
        if command.type != "session.configuration.update":
            raise CommandRejected("unsupported_configuration_command")
        service = SessionConfigurationService(self._db)
        try:
            current = await service.current(session_id)
            if current.version != command.payload.expected_configuration_version:
                raise ConfigurationError("stale_configuration_version", "Configuration version is stale; refresh and retry.")
            consequences = await service.consequences(session_id, current, command.payload.patch)
            if consequences.requires_confirmation and not command.payload.confirm_consequences:
                return [(
                    "error.created", "system", {
                        "errorId": f"configuration_preview_{command.command_id}",
                        "code": "configuration_preview_required", "summary": consequences.summary,
                        "recoverable": True,
                    },
                )], ()
            snapshot, consequences = await service.update(
                session_id, command.payload.expected_configuration_version, command.payload.patch,
            )
        except ConfigurationError as error:
            raise CommandRejected(error.code) from error
        changed = [field for field in command.payload.patch.model_fields_set]
        specs: list[tuple[str, str, dict[str, Any]]] = [(
            "session.configuration_updated", "human", {
                "configurationVersion": snapshot.version, "previousPolicyHash": current.policy_hash,
                "policyHash": snapshot.policy_hash, "changedFields": changed,
            },
        )]
        for assignment_id in consequences.invalid_assignment_ids:
            specs.append(("assignment.cancelled", "system", {
                "assignmentId": assignment_id,
                "reasonSummary": "Interrupted because the confirmed session configuration no longer permits this work.",
            }))
        return specs, consequences.invalid_assignment_ids

    def _status_spec(self, current: str, target: str, reason: str) -> tuple[str, str, dict[str, Any]]:
        self._require_transition(current, target)
        return ("session.status_changed", "human", {"status": target, "reasonSummary": reason})


def event_wire_value(event: StoredEvent) -> dict[str, Any]:
    """Translate a persisted event into the canonical, generated wire shape."""

    from datetime import UTC, datetime

    raw = {
        "version": 1,
        "eventId": event.event_id,
        "sessionId": event.session_id,
        "sequence": event.sequence,
        "timestamp": datetime.fromtimestamp(event.timestamp_ms / 1000, UTC).isoformat().replace("+00:00", "Z"),
        "type": event.event_type,
        "actorId": event.actor_id,
        **({"correlationId": event.correlation_id} if event.correlation_id is not None else {}),
        "payload": event.payload,
    }
    # A malformed persisted row must not become an untrusted canonical response.
    from app.schemas.session_events import parse_session_event
    return parse_session_event(raw).model_dump(by_alias=True, mode="json", exclude_none=True)
