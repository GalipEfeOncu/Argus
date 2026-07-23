"""Repository boundary for SQLite orchestration state.

HTTP and WebSocket handlers use these methods rather than composing control-plane
SQL.  Each mutating operation states its transaction boundary explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
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
    actor_id: str
    correlation_id: str | None
    command_id: str | None
    payload: dict[str, Any]
    timestamp_ms: int


@dataclass(frozen=True)
class EventPage:
    """A bounded, cursor-addressable portion of a session timeline."""

    events: tuple[StoredEvent, ...]
    next_after_sequence: int | None


@dataclass(frozen=True)
class StoredSnapshot:
    id: str
    session_id: str
    last_sequence: int
    projection: dict[str, Any]
    checksum: str


class SnapshotChecksumMismatch(ValueError):
    """A persisted snapshot no longer matches its deterministic checksum."""


@dataclass(frozen=True)
class ArtifactPage:
    items: tuple[dict[str, Any], ...]
    next_cursor: tuple[int, str] | None


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
            # Sequence zero is reserved for the initial snapshot cursor.  This
            # keeps the live transport and the existing projection reducer in
            # lockstep: the first durable event is sequence one.
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM events WHERE session_id = ?", (session_id,)
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
        return StoredEvent(
            event_id, session_id, next_sequence, event_type, actor_id, correlation_id,
            command_id, payload, timestamp_ms,
        )

    @staticmethod
    def _stored_event(row: aiosqlite.Row) -> StoredEvent:
        return StoredEvent(
            row["id"], row["session_id"], row["sequence"], row["event_type"], row["actor_id"],
            row["correlation_id"], row["command_id"], json.loads(row["payload_json"]), row["timestamp_ms"],
        )

    async def list_for_session(self, session_id: str) -> list[StoredEvent]:
        """Return all events only for offline projection rebuilding, never an interactive route."""
        async with self._db.execute(
            """SELECT id, session_id, sequence, event_type, actor_id, correlation_id, command_id,
               payload_json, timestamp_ms FROM events WHERE session_id = ? ORDER BY sequence""",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._stored_event(row) for row in rows]

    async def page_after(
        self, session_id: str, *, after_sequence: int, limit: int = 200,
    ) -> EventPage:
        """Read a bounded timeline page using the indexed session/sequence cursor."""

        if after_sequence < -1:
            raise ValueError("after_sequence must be at least -1")
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        async with self._db.execute(
            """SELECT id, session_id, sequence, event_type, actor_id, correlation_id, command_id,
               payload_json, timestamp_ms
               FROM events WHERE session_id = ? AND sequence > ?
               ORDER BY sequence LIMIT ?""",
            (session_id, after_sequence, limit + 1),
        ) as cursor:
            rows = await cursor.fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        events = tuple(self._stored_event(row) for row in selected)
        return EventPage(events, events[-1].sequence if has_more and events else None)

    async def event_for_command(self, session_id: str, command_id: str) -> StoredEvent | None:
        async with self._db.execute(
            """SELECT e.id, e.session_id, e.sequence, e.event_type, e.actor_id, e.correlation_id,
               e.command_id, e.payload_json, e.timestamp_ms
               FROM command_receipts r JOIN events e ON e.id = r.outcome_event_id
               WHERE r.session_id = ? AND r.command_id = ?""",
            (session_id, command_id),
        ) as cursor:
            row = await cursor.fetchone()
        return self._stored_event(row) if row is not None else None

    async def events_for_command(self, session_id: str, command_id: str) -> tuple[StoredEvent, ...]:
        """Return the complete committed outcome for an idempotent command retry."""

        async with self._db.execute(
            "SELECT outcome_event_ids_json FROM command_receipts WHERE session_id = ? AND command_id = ?",
            (session_id, command_id),
        ) as cursor:
            receipt = await cursor.fetchone()
        if receipt is None:
            return ()
        event_ids = json.loads(receipt["outcome_event_ids_json"])
        if not event_ids:
            event = await self.event_for_command(session_id, command_id)
            return () if event is None else (event,)
        events: list[StoredEvent] = []
        for event_id in event_ids:
            async with self._db.execute(
                """SELECT id, session_id, sequence, event_type, actor_id, correlation_id, command_id,
                   payload_json, timestamp_ms FROM events WHERE id = ? AND session_id = ?""",
                (event_id, session_id),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise SnapshotChecksumMismatch("command receipt references a missing event")
            events.append(self._stored_event(row))
        return tuple(events)

    async def last_sequence(self, session_id: str) -> int:
        """Return event metadata without loading a timeline projection."""

        async with self._db.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS last_sequence FROM events WHERE session_id = ?", (session_id,)
        ) as cursor:
            return int((await cursor.fetchone())["last_sequence"])

    async def create_snapshot(self, session_id: str, *, snapshot_id: str | None = None) -> StoredSnapshot | None:
        """Persist a checksummed projection at a durable event boundary."""

        async with transaction(self._db):
            projection = await self._projection_from_events(session_id)
            if projection["lastSequence"] < 0:
                return None
            projection_json = _safe_json(projection)
            checksum = sha256(projection_json.encode()).hexdigest()
            snapshot_id = snapshot_id or str(uuid.uuid4())
            await self._db.execute(
                """INSERT OR IGNORE INTO event_snapshots
                   (id, session_id, last_sequence, projection_json, projection_checksum, created_at_ms)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (snapshot_id, session_id, projection["lastSequence"], projection_json, checksum, _now_ms()),
            )
            async with self._db.execute(
                """SELECT id, session_id, last_sequence, projection_json, projection_checksum
                   FROM event_snapshots WHERE session_id = ? AND projection_checksum = ?""",
                (session_id, checksum),
            ) as cursor:
                row = await cursor.fetchone()
            assert row is not None
            return self._stored_snapshot(row)

    async def latest_snapshot(self, session_id: str, *, at_or_before: int | None = None) -> StoredSnapshot | None:
        query = """SELECT id, session_id, last_sequence, projection_json, projection_checksum
                   FROM event_snapshots WHERE session_id = ?"""
        args: tuple[Any, ...] = (session_id,)
        if at_or_before is not None:
            query += " AND last_sequence <= ?"
            args = (session_id, at_or_before)
        query += " ORDER BY last_sequence DESC LIMIT 1"
        async with self._db.execute(query, args) as cursor:
            row = await cursor.fetchone()
        return None if row is None else self._stored_snapshot(row)

    @staticmethod
    def _stored_snapshot(row: aiosqlite.Row) -> StoredSnapshot:
        projection = json.loads(row["projection_json"])
        actual_checksum = sha256(_safe_json(projection).encode()).hexdigest()
        if actual_checksum != row["projection_checksum"]:
            raise SnapshotChecksumMismatch("snapshot projection checksum mismatch")
        return StoredSnapshot(
            row["id"], row["session_id"], row["last_sequence"], projection, row["projection_checksum"],
        )

    async def page_artifact_summaries(
        self, session_id: str, *, before: tuple[int, str] | None = None, limit: int = 100,
    ) -> ArtifactPage:
        """Read artifact metadata without hydrating artifacts or the event log."""

        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        query = """SELECT id, kind, relative_path, checksum, metadata_json, created_at_ms
                   FROM artifacts WHERE session_id = ?"""
        args: list[Any] = [session_id]
        if before is not None:
            query += " AND (created_at_ms < ? OR (created_at_ms = ? AND id < ?))"
            args.extend((before[0], before[0], before[1]))
        query += " ORDER BY created_at_ms DESC, id DESC LIMIT ?"
        args.append(limit + 1)
        async with self._db.execute(query, tuple(args)) as cursor:
            rows = await cursor.fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        items = tuple({
            "id": row["id"], "kind": row["kind"], "relativePath": row["relative_path"],
            "checksum": row["checksum"], "metadata": json.loads(row["metadata_json"]),
            "createdAtMs": row["created_at_ms"],
        } for row in selected)
        cursor_value = (selected[-1]["created_at_ms"], selected[-1]["id"]) if has_more and selected else None
        return ArtifactPage(items, cursor_value)

    async def _projection_from_events(self, session_id: str) -> dict[str, Any]:
        status = "created"
        last_sequence = -1
        for event in await self.list_for_session(session_id):
            last_sequence = event.sequence
            if event.event_type == "session.status_changed" and isinstance(event.payload.get("status"), str):
                status = event.payload["status"]
        return {"sessionId": session_id, "status": status, "lastSequence": last_sequence}

    async def rebuild_session_projection(self, session_id: str) -> dict[str, Any]:
        """Derive the Phase-2 read model solely from immutable events."""

        async with transaction(self._db):
            projection = await self._projection_from_events(session_id)
            await self._db.execute(
                "UPDATE sessions SET status = ?, updated_at_ms = ? WHERE id = ?",
                (projection["status"], _now_ms(), session_id),
            )
            return projection
