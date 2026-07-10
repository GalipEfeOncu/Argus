from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import sessions, providers, models_router, websocket as ws_router
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure DB directory and tables exist
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    await init_db()
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
app.include_router(providers.router, prefix="/providers", tags=["providers"])
app.include_router(models_router.router, prefix="/models", tags=["models"])
app.include_router(ws_router.router, tags=["websocket"])


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
