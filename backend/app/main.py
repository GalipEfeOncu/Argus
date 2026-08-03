from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import agent_definitions, contracts, models_router, projects, providers, runtime, sessions, skills, websocket as ws_router
from app.db.database import init_db
from app.db.database import get_db
from app.db.repositories import _now_ms
from app.services.workspace_service import ProjectWorkspaceService
from app.services.agent_definition_service import AgentDefinitionService
from app.services.recovery_service import RecoveryService
from app.services.observability_service import observability


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure DB directory and tables exist
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    await init_db()
    db = await get_db()
    try:
        await AgentDefinitionService(db).ensure_builtin_templates()
        await ProjectWorkspaceService(db, managed_root=Path(settings.db_path).expanduser().resolve().parent / "workspaces").recover_after_restart()
        report = await RecoveryService(db).recover_after_restart()
        observability.record("INFO", "runtime.recovery_checked", {"sessions": report.sessions, "orphanedAttempts": report.orphaned_attempts})
        print(f"[Argus] Recovery checked {report.sessions} sessions; orphaned attempts={report.orphaned_attempts}")
    finally:
        await db.close()
    print(f"[Argus] Backend ready on {settings.host}:{settings.port}")
    yield
    # Shutdown: cleanup
    print("[Argus] Shutting down")


app = FastAPI(
    title="Argus Backend",
    version="0.1.0",
    description="Multi-Agent Orchestration Backend",
    lifespan=lifespan,
)

# CORS — allow Tauri webview and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost:1420", "http://127.0.0.1:1420"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
app.include_router(agent_definitions.router, prefix="/agent-definitions", tags=["agent-definitions"])
app.include_router(skills.router, prefix="/skills", tags=["skills"])
app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(providers.router, prefix="/providers", tags=["providers"])
app.include_router(models_router.router, prefix="/models", tags=["models"])
app.include_router(contracts.router, prefix="/contracts", tags=["contracts"])
app.include_router(ws_router.router, tags=["websocket"])
app.include_router(runtime.router, prefix="/runtime", tags=["runtime"])


@app.middleware("http")
async def structured_request_log(request, call_next):
    """Emit path-level local telemetry without headers, query values, or bodies."""

    started = _now_ms()
    try:
        response = await call_next(request)
    except Exception:
        observability.record("ERROR", "http.request_failed", {"method": request.method, "durationMs": _now_ms() - started})
        raise
    observability.record("INFO", "http.request_completed", {"method": request.method, "statusCode": response.status_code, "durationMs": _now_ms() - started})
    return response


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
