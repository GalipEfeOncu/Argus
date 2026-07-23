from pydantic import BaseModel
from typing import Optional
from enum import Enum
from app.schemas.project import WorkspaceMode


class SessionStatus(str, Enum):
    setup = "setup"
    running = "running"
    paused = "paused"
    waiting_approval = "waiting_approval"
    completed = "completed"
    error = "error"


class RoleConfigSchema(BaseModel):
    role: str
    enabled: bool = True
    provider_id: str
    model_id: str
    custom_system_prompt: Optional[str] = None


class SessionCreateRequest(BaseModel):
    project_path: str
    task: str
    role_configs: list[RoleConfigSchema]
    name: Optional[str] = None
    workspace_mode: WorkspaceMode | None = None
    acknowledge_direct_write: bool = False


class SessionResponse(BaseModel):
    id: str
    name: str
    project_path: str
    task: str
    status: SessionStatus
    started_at: float
    completed_at: Optional[float] = None
