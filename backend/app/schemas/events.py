from pydantic import BaseModel
from typing import Any, Optional
from enum import Enum


class WSEventType(str, Enum):
    agent_start = "agent_start"
    agent_done = "agent_done"
    token = "token"
    tool_call_start = "tool_call_start"
    tool_call_result = "tool_call_result"
    diff = "diff"
    interrupt = "interrupt"
    error = "error"
    session_complete = "session_complete"


class WSEvent(BaseModel):
    type: WSEventType
    session_id: str
    agent_role: Optional[str] = None
    content: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    timestamp: float

    @classmethod
    def token(cls, session_id: str, agent_role: str, content: str, ts: float):
        return cls(type=WSEventType.token, session_id=session_id, agent_role=agent_role, content=content, timestamp=ts)

    @classmethod
    def agent_start(cls, session_id: str, agent_role: str, ts: float):
        return cls(type=WSEventType.agent_start, session_id=session_id, agent_role=agent_role, timestamp=ts)

    @classmethod
    def agent_done(cls, session_id: str, agent_role: str, ts: float):
        return cls(type=WSEventType.agent_done, session_id=session_id, agent_role=agent_role, timestamp=ts)

    @classmethod
    def tool_call_start(cls, session_id: str, agent_role: str, data: dict, ts: float):
        return cls(type=WSEventType.tool_call_start, session_id=session_id, agent_role=agent_role, data=data, timestamp=ts)

    @classmethod
    def interrupt_event(cls, session_id: str, reason: str, message: str, ts: float):
        return cls(type=WSEventType.interrupt, session_id=session_id, data={"reason": reason, "message": message}, timestamp=ts)
