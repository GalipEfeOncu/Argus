"""Redacted local diagnostics without expanding Argus's data-retention surface."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
from typing import Any

import aiosqlite

from app.db.repositories import _SENSITIVE_KEY, _SENSITIVE_VALUE, _now_ms


_PROMPT_OR_REASONING_KEY = re.compile(r"(?:prompt|message|content|reasoning|task|goal|file[_-]?content)", re.I)
_LOCATION_KEY = re.compile(r"(?:path|workspace|directory|project|file(?:name)?)", re.I)
_DATABASE_LOCK = re.compile(r"(?:database|sqlite).*(?:locked|busy)|(?:locked|busy).*(?:database|sqlite)", re.I)
_SAFE_TEXT_KEYS = frozenset({"errorClass", "method", "status", "statusCode"})
_MAX_LOGS = 200
_MIN_FREE_BYTES = 50 * 1024 * 1024


def _safe_public_label(value: object, *, fallback: str = "redacted") -> str:
    candidate = value if isinstance(value, str) else ""
    return candidate[:160] if re.fullmatch(r"[a-z][a-z0-9_.-]{0,159}", candidate[:160]) and not _SENSITIVE_KEY.search(candidate) and not _SENSITIVE_VALUE.search(candidate) else fallback


def _redact(value: Any, *, key: str | None = None) -> Any:
    """Preserve useful shape while removing credentials and user content."""

    if key is not None and (_SENSITIVE_KEY.search(key) or _PROMPT_OR_REASONING_KEY.search(key) or _LOCATION_KEY.search(key)):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key)[:80]: _redact(item, key=str(item_key)) for item_key, item in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value[:50]]
    if isinstance(value, str):
        return value[:100] if key in _SAFE_TEXT_KEYS and not _SENSITIVE_VALUE.search(value) else "[REDACTED]"
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return "[REDACTED]"


@dataclass(frozen=True)
class _LogEntry:
    timestamp_ms: int
    level: str
    event: str
    details: dict[str, object]


class LocalObservability:
    """Process-local structured logs and SQL-derived, non-content diagnostics."""

    def __init__(self) -> None:
        self._entries: deque[_LogEntry] = deque(maxlen=_MAX_LOGS)

    def record(self, level: str, event: str, details: dict[str, object] | None = None) -> None:
        safe_level = level if level in {"INFO", "WARNING", "ERROR"} else "INFO"
        safe_event = _safe_public_label(event, fallback="runtime.event")
        safe_details = _redact(details or {})
        assert isinstance(safe_details, dict)
        self._entries.append(_LogEntry(_now_ms(), safe_level, safe_event, safe_details))
        logging.getLogger("argus.runtime").log(
            getattr(logging, safe_level), json.dumps({"event": safe_event, "details": safe_details}, sort_keys=True),
        )

    def logs(self) -> list[dict[str, object]]:
        return [{"timestampMs": entry.timestamp_ms, "level": entry.level, "event": entry.event, "details": entry.details} for entry in self._entries]

    async def health(self, db: aiosqlite.Connection, *, db_path: str) -> dict[str, object]:
        now = _now_ms()
        checks: list[dict[str, object]] = []
        database_ok = await self._database_check(db, checks)
        await self._disk_check(db_path, checks)
        invalid_payloads = await self._invalid_event_count(db, checks) if database_ok else 0
        if database_ok:
            try:
                queues = await self._queues(db)
                leases = await self._leases(db, now)
                provider_latency = await self._provider_latency(db, since_ms=now - 86_400_000)
                event_lag = await self._event_lag(db, now, invalid_payloads)
                usage = await self._usage(db)
            except aiosqlite.DatabaseError as error:
                database_ok = False
                code = "database_locked" if _DATABASE_LOCK.search(str(error)) else "database_unavailable"
                checks.append(self._check(code, "degraded", "Local database became unavailable while diagnostics were collected.", "Wait for the database to become available, then refresh diagnostics."))
                self.record("WARNING", "runtime.diagnostics_interrupted", {"errorClass": type(error).__name__})
        if not database_ok:
            queues = self._empty_queues()
            leases = {"active": 0, "expiredUnreleased": 0}
            provider_latency = []
            event_lag = {"newestEventAgeMs": None, "sessionsWithEvents": 0, "invalidPayloads": invalid_payloads}
            usage = {"inputTokens": 0, "outputTokens": 0, "normalizedCost": None, "durationMs": 0, "samples": 0}
        if database_ok:
            checks.extend(self._provider_check(provider_latency))
            if invalid_payloads == 0:
                checks.append(self._check("event_integrity", "ok", "Stored event payloads are valid JSON."))
        status = "degraded" if any(check["status"] == "degraded" for check in checks) else "healthy"
        return {
            "status": status, "observedAtMs": now, "checks": checks, "queues": queues,
            "writerLeases": leases, "providerLatency": provider_latency, "eventLag": event_lag, "usage": usage,
        }

    async def support_bundle(self, db: aiosqlite.Connection, *, db_path: str, session_ids: list[str] | None = None) -> dict[str, object]:
        runtime = await self.health(db, db_path=db_path)
        try:
            sessions = await self._session_summaries(db, session_ids or [])
        except aiosqlite.DatabaseError as error:
            sessions = []
            self.record("WARNING", "runtime.support_bundle_session_summary_unavailable", {"errorClass": type(error).__name__})
        return {
            "formatVersion": 1,
            "createdAtMs": _now_ms(),
            "runtime": runtime,
            "sessions": sessions,
            "logs": self.logs(),
            "excluded": [
                "credentials and credential references", "raw prompts, messages, and private reasoning",
                "project paths and project file contents", "event payload bodies",
            ],
        }

    @staticmethod
    def _check(code: str, status: str, summary: str, action: str | None = None) -> dict[str, object]:
        return {"code": code, "status": status, "summary": summary, "action": action}

    async def _database_check(self, db: aiosqlite.Connection, checks: list[dict[str, object]]) -> bool:
        try:
            async with db.execute("PRAGMA integrity_check") as cursor:
                row = await cursor.fetchone()
            if row is None or str(row[0]).lower() != "ok":
                checks.append(self._check("database_corrupt", "degraded", "SQLite integrity check did not pass.", "Stop active work and restore the local database from a backup before continuing."))
                return False
            checks.append(self._check("database", "ok", "Local database is available."))
            return True
        except aiosqlite.DatabaseError as error:
            code = "database_locked" if _DATABASE_LOCK.search(str(error)) else "database_unavailable"
            checks.append(self._check(code, "degraded", "Local database is temporarily unavailable.", "Wait for another local process to release the database, then refresh diagnostics."))
            self.record("WARNING", "runtime.database_unavailable", {"errorClass": type(error).__name__})
            return False

    async def _disk_check(self, db_path: str, checks: list[dict[str, object]]) -> None:
        try:
            stat = os.statvfs(Path(db_path).expanduser().resolve().parent)
            free_bytes = stat.f_bavail * stat.f_frsize
            if free_bytes < _MIN_FREE_BYTES:
                checks.append(self._check("disk_space_low", "degraded", "Local storage is nearly full.", "Free disk space before starting or applying more work."))
            else:
                checks.append(self._check("disk", "ok", "Local storage has sufficient free space."))
        except OSError as error:
            checks.append(self._check("disk_unavailable", "degraded", "Local storage could not be checked.", "Confirm the Argus data location is available and writable."))
            self.record("WARNING", "runtime.disk_unavailable", {"errorClass": type(error).__name__})

    async def _invalid_event_count(self, db: aiosqlite.Connection, checks: list[dict[str, object]]) -> int:
        try:
            async with db.execute("SELECT COUNT(*) AS count FROM events WHERE json_valid(payload_json) = 0") as cursor:
                count = int((await cursor.fetchone())["count"])
        except aiosqlite.DatabaseError:
            count = 1
        if count:
            checks.append(self._check("corrupted_event", "degraded", "One or more stored events cannot be read safely.", "Do not apply a result from the affected session; export diagnostics and recover the local database."))
        return count

    @staticmethod
    def _empty_queues() -> dict[str, int]:
        return {"runnableAssignments": 0, "activeToolExecutions": 0, "activeProviderOperations": 0, "pendingApprovals": 0, "pendingDecisions": 0, "reservedLimits": 0}

    async def _count(self, db: aiosqlite.Connection, query: str) -> int:
        async with db.execute(query) as cursor:
            row = await cursor.fetchone()
        return int(row["count"])

    async def _queues(self, db: aiosqlite.Connection) -> dict[str, int]:
        return {
            "runnableAssignments": await self._count(db, "SELECT COUNT(*) AS count FROM assignment_attempts WHERE state = 'running'"),
            "activeToolExecutions": await self._count(db, "SELECT COUNT(*) AS count FROM tool_executions WHERE exit_state IN ('requested', 'running')"),
            "activeProviderOperations": await self._count(db, "SELECT COUNT(*) AS count FROM provider_operations WHERE state IN ('pending', 'running')"),
            "pendingApprovals": await self._count(db, "SELECT COUNT(*) AS count FROM approvals WHERE decision = 'pending' OR decision IS NULL"),
            "pendingDecisions": await self._count(db, "SELECT COUNT(*) AS count FROM limit_resolution_requests WHERE state IN ('pending', 'claimed')"),
            "reservedLimits": await self._count(db, "SELECT COUNT(*) AS count FROM limit_reservations WHERE state = 'reserved'"),
        }

    async def _leases(self, db: aiosqlite.Connection, now: int) -> dict[str, int]:
        async with db.execute("SELECT COUNT(*) AS count FROM writer_leases WHERE released_at_ms IS NULL AND expires_at_ms > ?", (now,)) as cursor:
            active = int((await cursor.fetchone())["count"])
        async with db.execute("SELECT COUNT(*) AS count FROM writer_leases WHERE released_at_ms IS NULL AND expires_at_ms <= ?", (now,)) as cursor:
            expired = int((await cursor.fetchone())["count"])
        return {"active": active, "expiredUnreleased": expired}

    async def _provider_latency(self, db: aiosqlite.Connection, *, since_ms: int) -> list[dict[str, object]]:
        query = """SELECT operation_kind, COUNT(*) AS completed,
            SUM(CASE WHEN state IN ('failed', 'outcome_unknown') THEN 1 ELSE 0 END) AS failed,
            AVG(CASE WHEN completed_at_ms IS NULL THEN NULL ELSE MAX(0, completed_at_ms - started_at_ms) END) AS average_latency,
            MAX(CASE WHEN completed_at_ms IS NULL THEN NULL ELSE MAX(0, completed_at_ms - started_at_ms) END) AS maximum_latency
            FROM provider_operations WHERE completed_at_ms IS NOT NULL AND completed_at_ms >= ? GROUP BY operation_kind ORDER BY operation_kind LIMIT 100"""
        async with db.execute(query, (since_ms,)) as cursor:
            rows = await cursor.fetchall()
        return [{"operationKind": str(row["operation_kind"]), "completed": int(row["completed"]), "failed": int(row["failed"] or 0),
                 "averageLatencyMs": None if row["average_latency"] is None else int(row["average_latency"]),
                 "maximumLatencyMs": None if row["maximum_latency"] is None else int(row["maximum_latency"])} for row in rows]

    def _provider_check(self, latency: list[dict[str, object]]) -> list[dict[str, object]]:
        failed = sum(int(item["failed"]) for item in latency)
        if failed:
            return [self._check("provider_outage", "degraded", "Recent provider operations did not complete successfully.", "Check the provider connection and credential-store availability, then retry through normal session controls.")]
        return [self._check("providers", "ok", "No completed provider-operation failures are recorded.")]

    async def _event_lag(self, db: aiosqlite.Connection, now: int, invalid_payloads: int) -> dict[str, object]:
        async with db.execute("SELECT MAX(timestamp_ms) AS newest, COUNT(DISTINCT session_id) AS sessions FROM events") as cursor:
            row = await cursor.fetchone()
        newest = row["newest"]
        return {"newestEventAgeMs": None if newest is None else max(0, now - int(newest)), "sessionsWithEvents": int(row["sessions"]), "invalidPayloads": invalid_payloads}

    async def _usage(self, db: aiosqlite.Connection) -> dict[str, object]:
        async with db.execute("SELECT payload_json FROM events WHERE event_type = 'usage.updated' ORDER BY sequence DESC LIMIT 5000") as cursor:
            rows = await cursor.fetchall()
        input_tokens = output_tokens = duration_ms = 0
        cost: float | None = 0.0
        samples = 0
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
                input_tokens += max(0, int(payload.get("inputTokens", 0)))
                output_tokens += max(0, int(payload.get("outputTokens", 0)))
                duration_ms += max(0, int(payload.get("durationMs", 0)))
                item_cost = payload.get("normalizedCost")
                if item_cost is None:
                    cost = None
                elif cost is not None:
                    cost += max(0.0, float(item_cost))
                samples += 1
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return {"inputTokens": input_tokens, "outputTokens": output_tokens, "normalizedCost": cost, "durationMs": duration_ms, "samples": samples}

    async def _session_summaries(self, db: aiosqlite.Connection, selected_ids: list[str]) -> list[dict[str, object]]:
        values = selected_ids[:25]
        query = "SELECT id, status FROM sessions"
        arguments: tuple[str, ...] = ()
        if values:
            query += f" WHERE id IN ({','.join('?' for _ in values)})"
            arguments = tuple(values)
        query += " ORDER BY updated_at_ms DESC LIMIT 25"
        async with db.execute(query, arguments) as cursor:
            sessions = await cursor.fetchall()
        summaries: list[dict[str, object]] = []
        for session in sessions:
            session_id = str(session["id"])
            async with db.execute("SELECT COALESCE(MAX(sequence), 0) AS last_sequence FROM events WHERE session_id = ?", (session_id,)) as cursor:
                last_sequence = int((await cursor.fetchone())["last_sequence"])
            async with db.execute("SELECT event_type, COUNT(*) AS count FROM events WHERE session_id = ? GROUP BY event_type LIMIT 100", (session_id,)) as cursor:
                counts: dict[str, int] = {}
                for row in await cursor.fetchall():
                    event_type = _safe_public_label(row["event_type"])
                    counts[event_type] = counts.get(event_type, 0) + int(row["count"])
            async with db.execute("SELECT version, available_agent_ids_json, required_role_rules_json, execution_limits_json, approval_behavior_json FROM session_configurations WHERE session_id = ? ORDER BY version DESC LIMIT 1", (session_id,)) as cursor:
                configuration = await cursor.fetchone()
            shape: dict[str, object] = {}
            if configuration is not None:
                shape = self._configuration_shape(configuration)
            summaries.append({"sessionId": session_id, "status": str(session["status"]), "lastSequence": last_sequence, "eventCounts": counts, "configurationShape": shape})
        return summaries

    @staticmethod
    def _configuration_shape(row: aiosqlite.Row) -> dict[str, object]:
        def sequence(column: str) -> list[object]:
            try:
                value = json.loads(str(row[column]))
                return value if isinstance(value, list) else []
            except json.JSONDecodeError:
                return []
        try:
            limits = json.loads(str(row["execution_limits_json"]))
            limit_names = sorted(str(key) for key in limits.keys()) if isinstance(limits, dict) else []
        except json.JSONDecodeError:
            limit_names = []
        try:
            policy = json.loads(str(row["approval_behavior_json"]))
            policy_keys = sorted(str(key) for key in policy.keys()) if isinstance(policy, dict) else []
        except json.JSONDecodeError:
            policy_keys = []
        roles = [_safe_public_label(item.get("role")) for item in sequence("required_role_rules_json") if isinstance(item, dict) and isinstance(item.get("role"), str)]
        return {"version": int(row["version"]), "availableAgentCount": len(sequence("available_agent_ids_json")), "requiredRoles": roles[:50], "limitNames": limit_names[:50], "approvalPolicyFields": policy_keys[:50]}


observability = LocalObservability()
