import asyncio
from datetime import datetime
import uuid
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from app.db.database import get_db
from app.db.repositories import EventRepository, SessionRepository
from app.schemas.session_commands import parse_session_command
from app.services.command_processor import CommandProcessor, CommandRejected, event_wire_value

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


connection_hub = SessionConnectionHub()


@router.websocket("/ws/sessions/{session_id}")
async def canonical_session_websocket(
    websocket: WebSocket, session_id: str, after_sequence: int = Query(default=0, ge=-1),
) -> None:
    """Canonical replayable transport; each command is committed before it is sent."""

    await websocket.accept()
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

        processor = CommandProcessor(db)
        while True:
            try:
                raw = await websocket.receive_json()
                command = parse_session_command(raw)
                outcome = await processor.process(session_id, command)
                # The transaction completed inside process before any send, so a
                # disconnect leaves a reconnectable original correlated result.
                await connection_hub.publish(session_id, [event_wire_value(event) for event in outcome.events])
            except WebSocketDisconnect:
                return
            except CommandRejected as error:
                await websocket.send_json({"error": str(error), "code": "command_rejected"})
            except Exception:
                # Invalid input is not persisted and exposes no internal detail.
                await websocket.send_json({"error": "Invalid command.", "code": "invalid_command"})
    finally:
        await connection_hub.remove(session_id, websocket)
        await db.close()
