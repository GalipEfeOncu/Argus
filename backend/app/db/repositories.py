"""Repository boundary for SQLite orchestration state.

HTTP and WebSocket handlers use these methods rather than composing control-plane
SQL.  Each mutating operation states its transaction boundary explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any
import uuid

import aiosqlite

from app.db.database import transaction


_SENSITIVE_KEY = re.compile(r"(?:credential|private[_-]?reasoning|api[_-]?key|secret|access[_-]?token|password)", re.I)
_SENSITIVE_VALUE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+|AIza[\w-]{20,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{12,}|"
    r"AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+\.)",
    re.I,
)


class UnsafePersistencePayload(ValueError):
    """Raised before a secret or private reasoning payload reaches SQLite."""


def _safe_json(value: Any) -> str:
    """Serialize bounded metadata only, rejecting recognizable sensitive material."""

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if _SENSITIVE_KEY.search(str(key)):
                    raise UnsafePersistencePayload(f"Sensitive field '{key}' cannot be persisted")
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        elif isinstance(item, str) and _SENSITIVE_VALUE.search(item):
            raise UnsafePersistencePayload("Recognizable secret material cannot be persisted")

    visit(value)
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _safe_text(value: str) -> str:
    if _SENSITIVE_VALUE.search(value):
        raise UnsafePersistencePayload("Recognizable secret material cannot be persisted")
    return value


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class LegacySession:
    id: str
    name: str
    project_path: str
    task: str
    role_configs_json: str
    status: str


class SessionRepository:
    """Queries and mutations for the transitional session endpoints."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def create_legacy_session(
        self, *, session_id: str, name: str, project_path: str, task: str, role_configs: list[dict[str, Any]]
    ) -> None:
        now_ms = _now_ms()
        safe_name = _safe_text(name)
        safe_project_path = _safe_text(project_path)
        safe_task = _safe_text(task)
        async with transaction(self._db):
            await self._db.execute(
                """INSERT INTO sessions (
                    id, name, project_path, task, status, role_configs, started_at,
                    goal, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, 'setup', ?, ?, ?, ?, ?)""",
                (
                    session_id, safe_name, safe_project_path, safe_task, _safe_json(role_configs),
                    now_ms, safe_task, now_ms, now_ms,
                ),
            )

    async def list_legacy_sessions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        async with self._db.execute(
            "SELECT id, name, status, started_at FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def get_legacy_session(self, session_id: str) -> dict[str, Any] | None:
        async with self._db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def get_runtime_session(self, session_id: str) -> LegacySession | None:
        async with self._db.execute(
            "SELECT id, name, project_path, task, role_configs, status FROM sessions WHERE id = ?", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return LegacySession(
            id=row["id"], name=row["name"], project_path=row["project_path"], task=row["task"],
            role_configs_json=row["role_configs"], status=row["status"],
        )

    async def set_status(self, session_id: str, status: str) -> bool:
        async with self._db.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)) as cursor:
            if await cursor.fetchone() is None:
                return False
        await EventRepository(self._db).append(
            event_id=str(uuid.uuid4()), session_id=session_id, event_type="session.status_changed",
            actor_id="system", payload={"status": status}, timestamp_ms=_now_ms(),
        )
        return True


@dataclass(frozen=True)
class StoredEvent:
    event_id: str
    session_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]


class EventRepository:
    """Append-only event access with a small rebuildable session read model."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def append(
        self, *, event_id: str, session_id: str, event_type: str, actor_id: str,
        payload: dict[str, Any], timestamp_ms: int, correlation_id: str | None = None,
        command_id: str | None = None,
    ) -> StoredEvent:
        """Allocate a per-session sequence and persist the immutable event together."""

        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or timestamp_ms < 0:
            raise ValueError("timestamp_ms must be a UTC epoch-millisecond value")
        payload_json = _safe_json(payload)
        async with transaction(self._db):
            return await self._append_in_transaction(
                event_id=event_id, session_id=session_id, event_type=event_type, actor_id=actor_id,
                payload=payload, payload_json=payload_json, timestamp_ms=timestamp_ms,
                correlation_id=correlation_id, command_id=command_id,
            )

    async def _append_in_transaction(
        self, *, event_id: str, session_id: str, event_type: str, actor_id: str,
        payload: dict[str, Any], payload_json: str, timestamp_ms: int,
        correlation_id: str | None, command_id: str | None,
    ) -> StoredEvent:
        """Append while the caller owns the transaction boundary."""

        async with self._db.execute(
            "SELECT COALESCE(MAX(sequence), -1) + 1 AS next_sequence FROM events WHERE session_id = ?", (session_id,)
        ) as cursor:
            next_sequence = (await cursor.fetchone())["next_sequence"]
        await self._db.execute(
            """INSERT INTO events (
                id, session_id, sequence, event_type, actor_id, correlation_id, command_id,
                payload_json, timestamp_ms, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, session_id, next_sequence, event_type, actor_id, correlation_id, command_id,
             payload_json, timestamp_ms, _now_ms()),
        )
        if event_type == "session.status_changed" and isinstance(payload.get("status"), str):
            await self._db.execute(
                "UPDATE sessions SET status = ?, updated_at_ms = ? WHERE id = ?",
                (payload["status"], _now_ms(), session_id),
            )
        return StoredEvent(event_id, session_id, next_sequence, event_type, payload)

    async def list_for_session(self, session_id: str) -> list[StoredEvent]:
        async with self._db.execute(
            "SELECT id, session_id, sequence, event_type, payload_json FROM events WHERE session_id = ? ORDER BY sequence",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [StoredEvent(row["id"], row["session_id"], row["sequence"], row["event_type"], json.loads(row["payload_json"])) for row in rows]

    async def rebuild_session_projection(self, session_id: str) -> dict[str, Any]:
        """Derive the Phase-2 read model solely from immutable events."""

        async with transaction(self._db):
            status = "setup"
            last_sequence = -1
            for event in await self.list_for_session(session_id):
                last_sequence = event.sequence
                if event.event_type == "session.status_changed":
                    candidate = event.payload.get("status")
                    if isinstance(candidate, str):
                        status = candidate
            await self._db.execute(
                "UPDATE sessions SET status = ?, updated_at_ms = ? WHERE id = ?", (status, _now_ms(), session_id)
            )
            return {"sessionId": session_id, "status": status, "lastSequence": last_sequence}
