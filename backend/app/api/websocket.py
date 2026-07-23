import json
import time
import asyncio
from datetime import datetime
import uuid
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from app.agents.graph import compile_graph
from app.tools.file_tools import read_file, write_file, edit_file, list_dir
from app.tools.shell_tools import shell_exec
from app.tools.search_tools import search_files
from app.tools.git_tools import git_status, git_diff, git_commit
from app.db.database import get_db
from app.db.repositories import EventRepository, SessionRepository
from app.schemas.session_commands import parse_session_command
from app.services.command_processor import CommandProcessor, CommandRejected, event_wire_value

router = APIRouter()

ALL_TOOLS = [read_file, write_file, edit_file, list_dir, shell_exec, search_files, git_status, git_diff, git_commit]


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


@router.websocket("/ws/session/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()

    try:
        # Load session config from DB
        db = await get_db()
        try:
            row = await SessionRepository(db).get_runtime_session(session_id)
        finally:
            await db.close()

        if not row:
            await websocket.send_json({"type": "error", "data": {"message": "Session not found"}})
            await websocket.close(1008)
            return

        role_configs_raw = json.loads(row.role_configs_json)
        project_path = row.project_path
        task = row.task

        # Compile graph
        graph = await compile_graph(session_id, role_configs_raw, tools=ALL_TOOLS)
        config = {"configurable": {"thread_id": session_id}}

        # Initial state
        initial_state = {
            "messages": [],
            "current_task": task,
            "plan": None,
            "code_changes": [],
            "review_status": None,
            "review_feedback": None,
            "test_results": [],
            "active_agent": "planner",
            "project_path": project_path,
            "files_context": {},
            "human_feedback": None,
            "human_approved": None,
            "tool_calls_log": [],
            "session_id": session_id,
            "iteration_count": 0,
            "max_iterations": 5,
        }

        async def send(event_dict: dict):
            try:
                await websocket.send_json(event_dict)
            except Exception:
                pass

        # Stream agent events
        async for event in graph.astream_events(initial_state, config=config, version="v2"):
            ts = time.time()
            event_name = event["event"]

            if event_name == "on_chat_model_stream":
                token = ""
                chunk = event["data"].get("chunk")
                if chunk and hasattr(chunk, "content"):
                    if isinstance(chunk.content, str):
                        token = chunk.content
                    elif isinstance(chunk.content, list):
                        for part in chunk.content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                token += part.get("text", "")
                if token:
                    metadata = event.get("metadata", {})
                    agent_role = metadata.get("langgraph_node", "unknown")
                    await send({"type": "token", "session_id": session_id,
                                "agent_role": agent_role, "content": token, "timestamp": ts})

            elif event_name == "on_chain_start" and event.get("name") in (
                "planner", "builder", "reviewer", "tester", "ui_agent"
            ):
                await send({"type": "agent_start", "session_id": session_id,
                             "agent_role": event["name"], "timestamp": ts})

            elif event_name == "on_chain_end" and event.get("name") in (
                "planner", "builder", "reviewer", "tester", "ui_agent"
            ):
                await send({"type": "agent_done", "session_id": session_id,
                             "agent_role": event["name"], "timestamp": ts})

            elif event_name == "on_tool_start":
                tool_name = event.get("name", "unknown")
                tool_input = event["data"].get("input", {})
                metadata = event.get("metadata", {})
                agent_role = metadata.get("langgraph_node", "unknown")
                tool_id = event.get("run_id", str(time.time()))
                await send({
                    "type": "tool_call_start", "session_id": session_id,
                    "agent_role": agent_role,
                    "data": {"id": str(tool_id), "tool": tool_name, "args": tool_input, "status": "running"},
                    "timestamp": ts
                })

            elif event_name == "on_tool_end":
                tool_output = str(event["data"].get("output", ""))
                tool_id = event.get("run_id", str(time.time()))
                await send({
                    "type": "tool_call_result", "session_id": session_id,
                    "data": {"toolCallId": str(tool_id), "result": tool_output[:2000], "duration": 0},
                    "timestamp": ts
                })

            # Check for user messages on websocket (non-blocking)
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=0.01)
                if data.get("type") == "interrupt":
                    break
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                return

        await send({"type": "session_complete", "session_id": session_id, "timestamp": time.time()})

        # Update session status in DB
        db = await get_db()
        try:
            await SessionRepository(db).set_status(session_id, "completed")
        finally:
            await db.close()

    except WebSocketDisconnect:
        print(f"[WS] Client disconnected from session {session_id}")
    except Exception as e:
        print(f"[WS] Error in session {session_id}: {e}")
        try:
            await websocket.send_json({"type": "error", "session_id": session_id,
                                        "data": {"message": str(e)}, "timestamp": time.time()})
        except Exception:
            pass
