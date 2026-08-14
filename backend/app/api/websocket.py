import asyncio
from datetime import datetime
import hmac
import uuid
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from app.db.database import get_db
from app.db.repositories import EventRepository, SessionRepository
from app.schemas.session_commands import parse_session_command
from app.services.command_processor import CommandProcessor, CommandRejected, event_wire_value
from app.services.first_vertical_task import FirstVerticalTaskRunner
from app.config import settings
from pathlib import Path

router = APIRouter()

class SessionConnectionHub:
    """In-process shared-room fan-out with bounded slow-client delivery."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def add(self, session_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.setdefault(session_id, set()).add(websocket)

    async def remove(self, session_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(session_id)
            if sockets is None:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(session_id, None)

    async def publish(self, session_id: str, values: list[dict]) -> None:
        """Broadcast committed events without allowing one slow peer to stall a room."""

        async with self._lock:
            sockets = tuple(self._connections.get(session_id, ()))
            failed: list[WebSocket] = []
            for socket in sockets:
                try:
                    for value in values:
                        await asyncio.wait_for(socket.send_json(value), timeout=0.25)
                except (TimeoutError, RuntimeError, WebSocketDisconnect):
                    failed.append(socket)
            for socket in failed:
                self._connections.get(session_id, set()).discard(socket)
            if session_id in self._connections and not self._connections[session_id]:
                self._connections.pop(session_id, None)

    async def connection_count(self) -> int:
        async with self._lock:
            return sum(len(sockets) for sockets in self._connections.values())


connection_hub = SessionConnectionHub()
_vertical_tasks: set[asyncio.Task[None]] = set()


def _schedule_first_vertical_step(session_id: str, *, after_grant: bool) -> None:
    """Keep worker tasks owned so application shutdown can drain them safely."""

    task = asyncio.create_task(_run_first_vertical_step(session_id, after_grant=after_grant))
    _vertical_tasks.add(task)
    task.add_done_callback(_vertical_tasks.discard)


async def shutdown_vertical_tasks(*, grace_period_seconds: float = 2.0) -> None:
    """Drain workers briefly, then cancel and await them before loop shutdown."""

    tasks = tuple(_vertical_tasks)
    if not tasks:
        return
    _, pending = await asyncio.wait(tasks, timeout=grace_period_seconds)
    for task in pending:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def _run_first_vertical_step(session_id: str, *, after_grant: bool) -> None:
    """Run the provider-neutral Phase 3.4 worker and fan out its committed events."""

    db = await get_db()
    try:
        events = EventRepository(db)
        before = await events.last_sequence(session_id)
        runner = FirstVerticalTaskRunner(
            db, managed_root=Path(settings.db_path).expanduser().resolve().parent / "workspaces",
        )
        if after_grant:
            await runner.run_after_grant(session_id)
        else:
            approval_id = await runner.request_scoped_write_grant(session_id)
            if approval_id is None:
                await runner.run_after_grant(session_id)
        committed = await events.page_after(session_id, after_sequence=before, limit=200)
        await connection_hub.publish(session_id, [event_wire_value(event) for event in committed.events])
    except (PermissionError, RuntimeError, ValueError) as error:
        # A cancellation may deliberately race the queued continuation; it is
        # already visible in the timeline and must not become a false failure.
        session = await SessionRepository(db).get_runtime_session(session_id)
        if session is not None and session.status != "cancelled":
            error_event = await EventRepository(db).append(
                event_id=f"vertical_error_{uuid.uuid4().hex}", session_id=session_id,
                event_type="error.created", actor_id="system",
                payload={"errorId": f"vertical_error_{uuid.uuid4().hex}", "code": "vertical_task_failed",
                         "summary": str(error), "recoverable": True},
                timestamp_ms=int(datetime.now().timestamp() * 1000),
            )
            await connection_hub.publish(session_id, [event_wire_value(error_event)])
    finally:
        await asyncio.shield(db.close())


@router.websocket("/ws/sessions/{session_id}")
async def canonical_session_websocket(
    websocket: WebSocket, session_id: str, after_sequence: int = Query(default=0, ge=-1),
) -> None:
    """Canonical replayable transport; each command is committed before it is sent."""

    allowed_origins = {origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()}
    origin = websocket.headers.get("origin")
    valid_origin = origin is None or origin in allowed_origins
    protocols = [value.strip() for value in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    access_token = next((value.removeprefix("argus.token.") for value in protocols if value.startswith("argus.token.")), None)
    valid_token = not settings.access_token or (
        access_token is not None and hmac.compare_digest(settings.access_token.encode(), access_token.encode())
    )
    if not valid_origin or not valid_token:
        await websocket.close(code=1008, reason="Native runtime authentication required")
        return
    await websocket.accept(subprotocol="argus.v1" if "argus.v1" in protocols else None)
    db = await get_db()
    try:
        session = await SessionRepository(db).get_runtime_session(session_id)
        if session is None:
            await websocket.close(code=1008, reason="Session not found")
            return
        events = EventRepository(db)
        page = await events.page_after(session_id, after_sequence=after_sequence)
        last_sequence = await events.last_sequence(session_id)
        status = {"setup": "created", "error": "failed"}.get(session.status, session.status)
        await websocket.send_json({
            "version": 1, "eventId": f"snapshot_{uuid.uuid4()}", "sessionId": session_id,
            "sequence": max(after_sequence, 0), "timestamp": datetime.now().astimezone().isoformat(),
            "type": "session.snapshot", "actorId": "system",
            "payload": {"status": status, "lastSequence": last_sequence},
        })
        for event in page.events:
            await websocket.send_json(event_wire_value(event))

        await connection_hub.add(session_id, websocket)
        # Events can commit while the initial replay is being sent.  Register
        # first, then close that cursor gap; any duplicate fan-out is safe
        # because the client reducer deduplicates immutable event IDs.
        replay_cursor = page.events[-1].sequence if page.events else after_sequence
        catchup = await events.page_after(session_id, after_sequence=replay_cursor)
        for event in catchup.events:
            await websocket.send_json(event_wire_value(event))

        processor = CommandProcessor(db)
        while True:
            try:
                raw = await websocket.receive_json()
                command = parse_session_command(raw)
                outcome = await processor.process(session_id, command)
                # The transaction completed inside process before any send, so a
                # disconnect leaves a reconnectable original correlated result.
                await connection_hub.publish(session_id, [event_wire_value(event) for event in outcome.events])
                if not outcome.duplicate and command.type == "session.start":
                    _schedule_first_vertical_step(session_id, after_grant=False)
                elif not outcome.duplicate and command.type == "approval.resolve" and command.payload.resolution == "grant":
                    _schedule_first_vertical_step(session_id, after_grant=True)
            except WebSocketDisconnect:
                return
            except CommandRejected as error:
                rejected = await EventRepository(db).append(
                    event_id=f"command_error_{uuid.uuid4().hex}", session_id=session_id,
                    event_type="error.created", actor_id="system",
                    payload={"errorId": f"command_error_{uuid.uuid4().hex}", "code": "command_rejected",
                             "summary": str(error), "recoverable": True},
                    timestamp_ms=int(datetime.now().timestamp() * 1000), correlation_id=command.command_id,
                )
                await connection_hub.publish(session_id, [event_wire_value(rejected)])
            except Exception:
                # Invalid input receives a canonical, redacted room error. It
                # never exposes parser or persistence details.
                invalid = await EventRepository(db).append(
                    event_id=f"invalid_command_{uuid.uuid4().hex}", session_id=session_id,
                    event_type="error.created", actor_id="system",
                    payload={"errorId": f"invalid_command_{uuid.uuid4().hex}", "code": "invalid_command",
                             "summary": "Invalid command.", "recoverable": True},
                    timestamp_ms=int(datetime.now().timestamp() * 1000),
                )
                await connection_hub.publish(session_id, [event_wire_value(invalid)])
    finally:
        await connection_hub.remove(session_id, websocket)
        await asyncio.shield(db.close())
