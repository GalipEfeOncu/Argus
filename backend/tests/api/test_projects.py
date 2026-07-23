from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_projects_endpoint_canonicalizes_registration_and_returns_safe_validation_errors(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "projects.db"))
    project = tmp_path / "project"
    project.mkdir()
    with TestClient(app) as client:
        created = client.post("/projects/", json={"path": str(project / "."), "displayName": "Demo"})
        listed = client.get("/projects/")
        invalid = client.post("/projects/", json={"path": str(tmp_path / "missing")})

    assert created.status_code == 201
    assert created.json()["canonicalPath"] == str(project.resolve())
    assert created.json()["displayName"] == "Demo"
    assert listed.status_code == 200 and listed.json()[0]["id"] == created.json()["id"]
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "unsupported_project"


def test_session_creation_prepares_a_default_isolated_workspace(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sessions.db"
    monkeypatch.setattr(settings, "db_path", str(database_path))
    project = tmp_path / "project"
    project.mkdir()
    with TestClient(app) as client:
        response = client.post("/sessions/", json={
            "project_path": str(project), "task": "Write a test", "role_configs": [],
        })

    assert response.status_code == 200
    with sqlite3.connect(database_path) as database:
        workspace = database.execute("SELECT mode, root_path FROM workspaces WHERE session_id = ?", (response.json()["id"],)).fetchone()
        session_path = database.execute("SELECT project_path FROM sessions WHERE id = ?", (response.json()["id"],)).fetchone()
    assert workspace is not None and workspace[0] == "snapshot"
    assert session_path is not None and session_path[0] == workspace[1]
    assert Path(workspace[1]).is_dir() and Path(workspace[1]) != project


def test_direct_write_session_requires_acknowledgement(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "direct.db"
    monkeypatch.setattr(settings, "db_path", str(database_path))
    project = tmp_path / "project"
    project.mkdir()
    with TestClient(app) as client:
        denied = client.post("/sessions/", json={
            "project_path": str(project), "task": "Change in place", "role_configs": [], "workspace_mode": "direct_write",
        })
        accepted = client.post("/sessions/", json={
            "project_path": str(project), "task": "Change in place", "role_configs": [],
            "workspace_mode": "direct_write", "acknowledge_direct_write": True,
        })

    assert denied.status_code == 422
    assert accepted.status_code == 200
    with sqlite3.connect(database_path) as database:
        mode = database.execute("SELECT mode FROM workspaces WHERE session_id = ?", (accepted.json()["id"],)).fetchone()
    assert mode == ("direct_write",)
