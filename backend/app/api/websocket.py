import json
import time
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.agents.graph import compile_graph
from app.tools.file_tools import read_file, write_file, edit_file, list_dir
from app.tools.shell_tools import shell_exec
from app.tools.search_tools import search_files
from app.tools.git_tools import git_status, git_diff, git_commit
from app.db.database import get_db
from app.schemas.events import WSEvent, WSEventType

router = APIRouter()

ALL_TOOLS = [read_file, write_file, edit_file, list_dir, shell_exec, search_files, git_status, git_diff, git_commit]


@router.websocket("/ws/session/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()

    try:
        # Load session config from DB
        async with await get_db() as db:
            async with db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cursor:
                row = await cursor.fetchone()

        if not row:
            await websocket.send_json({"type": "error", "data": {"message": "Session not found"}})
            await websocket.close(1008)
            return

        role_configs_raw = json.loads(row["role_configs"])
        project_path = row["project_path"]
        task = row["task"]

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
        async with await get_db() as db:
            await db.execute("UPDATE sessions SET status = 'completed' WHERE id = ?", (session_id,))
            await db.commit()

    except WebSocketDisconnect:
        print(f"[WS] Client disconnected from session {session_id}")
    except Exception as e:
        print(f"[WS] Error in session {session_id}: {e}")
        try:
            await websocket.send_json({"type": "error", "session_id": session_id,
                                        "data": {"message": str(e)}, "timestamp": time.time()})
        except Exception:
            pass
