from contextlib import asynccontextmanager
from pathlib import Path

import hmac

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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
from app.version import APP_VERSION


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
    try:
        yield
    finally:
        await ws_router.shutdown_vertical_tasks()
        print("[Argus] Shutting down")


app = FastAPI(
    title="Argus Backend",
    version=APP_VERSION,
    description="Multi-Agent Orchestration Backend",
    lifespan=lifespan,
)

# CORS — allow Tauri webview and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def protect_local_runtime(request: Request, call_next):
    """Bind the localhost API to the native shell that launched this process."""

    allowed_origins = {origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()}
    origin = request.headers.get("origin")
    if origin is not None and origin not in allowed_origins:
        return JSONResponse(status_code=403, content={"detail": "Unexpected request origin."})
    if request.method == "OPTIONS" and origin is not None:
        return await call_next(request)
    expected = settings.access_token
    if expected:
        authorization = request.headers.get("authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(expected.encode(), supplied.encode()):
            return JSONResponse(status_code=401, content={"detail": "Native runtime authentication required."})
    return await call_next(request)

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
    return {"status": "ok", "version": APP_VERSION}
