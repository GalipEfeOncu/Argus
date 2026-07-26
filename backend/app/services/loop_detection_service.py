"""Durable, redacted loop signals for findings, failures, and no-progress work."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any, Literal
import uuid

import aiosqlite

from app.db.repositories import EventRepository, _SENSITIVE_VALUE, _now_ms, _safe_json
from app.services.budget_counter_service import BudgetCounterService
from app.services.session_configuration_service import SessionConfigurationService


SignalKind = Literal["review_finding", "failure", "no_progress"]
_STOP_WORDS = frozenset({"a", "an", "and", "at", "by", "found", "has", "in", "is", "issue", "of", "on", "review", "the", "to", "with"})
_TOKEN = re.compile(r"[a-z0-9_./:-]+")


@dataclass(frozen=True)
class LoopSignal:
    kind: SignalKind
    fingerprint: str
    occurrence_count: int
    assignment_id: str | None

    @property
    def reached(self) -> bool:
        """The first observation is evidence; the second is a loop."""

        return self.occurrence_count >= 2


class LoopDetectionService:
    """Keep only stable SHA-256 fingerprints, never review prose or tool output."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._events = EventRepository(db)

    @staticmethod
    def finding_fingerprint(finding: object) -> str:
        """Normalize stable structured review fields; prose is a last-resort token set."""

        if isinstance(finding, dict):
            stable = [
                str(finding.get(key, ""))
                for key in ("category", "ruleId", "rule_id", "path", "filePath", "file_path", "symbol", "line", "lineAnchor", "line_anchor")
                if finding.get(key) is not None
            ]
            # Older reviewer evidence only has prose.  Token ordering makes
            # small wording/order changes stable without retaining that prose.
            if not stable:
                stable.append(str(finding.get("message", finding.get("summary", finding.get("title", "")))))
        else:
            stable = [str(finding)]
        return LoopDetectionService._fingerprint("review_finding", stable)

    @staticmethod
    def failure_fingerprint(code: str, summary: str) -> str:
        return LoopDetectionService._fingerprint("failure", (code, summary))

    @staticmethod
    def progress_fingerprint(workspace_checksum: str, diff_checksum: str | None = None) -> str:
        return LoopDetectionService._fingerprint("no_progress", (workspace_checksum, diff_checksum or workspace_checksum))

    @staticmethod
    def _fingerprint(kind: str, values: object) -> str:
        if isinstance(values, str):
            values = (values,)
        normalized: list[str] = []
        for value in values:  # type: ignore[union-attr]
            redacted = _SENSITIVE_VALUE.sub("secret", str(value).lower())
            tokens = sorted({token for token in _TOKEN.findall(redacted) if token not in _STOP_WORDS})
            normalized.append(" ".join(tokens))
        material = f"{kind}|" + "|".join(normalized)
        return sha256(material.encode("utf-8")).hexdigest()

    async def record_review_evidence_in_transaction(
        self, session_id: str, assignment_id: str, evidence: list[dict[str, Any]],
    ) -> tuple[LoopSignal, ...]:
        signals: list[LoopSignal] = []
        async with self._db.execute(
            """SELECT agent.role FROM assignments assignment JOIN session_agents agent
               ON agent.id = assignment.assignee_session_agent_id WHERE assignment.id = ? AND assignment.session_id = ?""",
            (assignment_id, session_id),
        ) as cursor:
            assignee = await cursor.fetchone()
        if assignee is None or assignee["role"] != "reviewer":
            return ()
        for item in evidence:
            data = item.get("data")
            if not isinstance(data, dict):
                continue
            findings = data.get("findings")
            if not isinstance(findings, list):
                continue
            for finding in findings:
                signals.append(await self._record_in_transaction(
                    session_id, "review_finding", self.finding_fingerprint(finding), assignment_id=assignment_id,
                ))
        return tuple(signals)

    async def record_failure_in_transaction(
        self, session_id: str, assignment_id: str, code: str, summary: str,
    ) -> LoopSignal:
        return await self._record_in_transaction(
            session_id, "failure", self.failure_fingerprint(code, summary), assignment_id=assignment_id,
        )

    async def record_no_progress_in_transaction(
        self, session_id: str, assignment_id: str, workspace_checksum: str, diff_checksum: str | None = None,
    ) -> LoopSignal:
        return await self._record_in_transaction(
            session_id, "no_progress", self.progress_fingerprint(workspace_checksum, diff_checksum),
            assignment_id=assignment_id, workspace_checksum=self.progress_fingerprint(workspace_checksum),
        )

    async def reserve_follow_up_revision_in_transaction(
        self, session_id: str, assignment_id: str, finding_fingerprint: str,
    ) -> None:
        """Reserve a revision only for a known finding before acceptance commits."""

        async with self._db.execute(
            "SELECT 1 FROM loop_signals WHERE session_id = ? AND signal_kind = 'review_finding' AND fingerprint = ?",
            (session_id, finding_fingerprint),
        ) as cursor:
            if await cursor.fetchone() is None:
                raise ValueError("unknown_finding_fingerprint")
        await BudgetCounterService(self._db).reserve_in_transaction(
            session_id, counter="revisions", scope_type="finding", scope_id=finding_fingerprint,
            # The assignment is deliberately not linked until the scheduler
            # has inserted it; the reservation table has a foreign key.
            assignment_id=None,
        )
    async def link_follow_up_in_transaction(
        self, session_id: str, assignment_id: str, finding_fingerprint: str,
    ) -> None:
        """Link the already-reserved accepted assignment to its finding."""

        await self._db.execute(
            """UPDATE limit_reservations SET assignment_id = ? WHERE id = (
                 SELECT id FROM limit_reservations WHERE session_id = ? AND counter_kind = 'revisions'
                   AND scope_id = ? AND assignment_id IS NULL AND state = 'consumed'
                 ORDER BY created_at_ms DESC, rowid DESC LIMIT 1
               )""",
            (assignment_id, session_id, finding_fingerprint),
        )
        await self._db.execute(
            "INSERT INTO finding_follow_ups (session_id, finding_fingerprint, assignment_id, accepted_at_ms) VALUES (?, ?, ?, ?)",
            (session_id, finding_fingerprint, assignment_id, _now_ms()),
        )

    async def finding_for_assignment(self, session_id: str, assignment_id: str) -> str | None:
        async with self._db.execute(
            "SELECT finding_fingerprint FROM finding_follow_ups WHERE session_id = ? AND assignment_id = ?",
            (session_id, assignment_id),
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else str(row["finding_fingerprint"])

    async def _record_in_transaction(
        self, session_id: str, kind: SignalKind, fingerprint: str, *, assignment_id: str | None,
        workspace_checksum: str | None = None,
    ) -> LoopSignal:
        now = _now_ms()
        async with self._db.execute(
            "SELECT occurrence_count FROM loop_signals WHERE session_id = ? AND signal_kind = ? AND fingerprint = ?",
            (session_id, kind, fingerprint),
        ) as cursor:
            existing = await cursor.fetchone()
        count = 1 if existing is None else int(existing["occurrence_count"]) + 1
        if existing is None:
            await self._db.execute(
                """INSERT INTO loop_signals (id, session_id, signal_kind, fingerprint, occurrence_count, last_assignment_id,
                   last_workspace_checksum, created_at_ms, updated_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"loop_{uuid.uuid4().hex}", session_id, kind, fingerprint, count, assignment_id, workspace_checksum, now, now),
            )
        else:
            await self._db.execute(
                """UPDATE loop_signals SET occurrence_count = ?, last_assignment_id = ?, last_workspace_checksum = ?, updated_at_ms = ?
                   WHERE session_id = ? AND signal_kind = ? AND fingerprint = ?""",
                (count, assignment_id, workspace_checksum, now, session_id, kind, fingerprint),
            )
        signal = LoopSignal(kind, fingerprint, count, assignment_id)
        if signal.reached:
            await self._append_reached_event_in_transaction(session_id, signal)
        return signal

    async def _append_reached_event_in_transaction(self, session_id: str, signal: LoopSignal) -> None:
        snapshot = await SessionConfigurationService(self._db).current(session_id)
        counter = {"review_finding": "repeated_finding", "failure": "repeated_failure", "no_progress": "no_progress"}[signal.kind]
        payload = {
            "counter": counter, "scopeId": signal.assignment_id or session_id,
            "current": float(signal.occurrence_count), "threshold": 2.0, "hard": True,
            "resolution": snapshot.approval_policy["limitResolution"], "fingerprint": signal.fingerprint,
            "occurrenceCount": signal.occurrence_count,
        }
        await self._events._append_in_transaction(
            event_id=f"loop_{uuid.uuid4().hex}", session_id=session_id, event_type="limit.reached", actor_id="system",
            payload=payload, payload_json=_safe_json(payload), timestamp_ms=_now_ms(), correlation_id=signal.assignment_id,
            command_id=None,
        )
