from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _configured_session_payload(client: TestClient, *, goal: str, **project: str) -> dict[str, object]:
    profile = client.post("/providers/", json={"providerKind": "openai", "displayName": "Configured provider"})
    assert profile.status_code == 201
    return {
        **project,
        "goal": goal,
        "coordinatorAgentId": "coordinator",
        "agents": [{
            "id": "coordinator",
            "role": "coordinator",
            "modelBinding": {"providerProfileId": profile.json()["id"], "modelId": "gpt-4o-mini"},
        }],
        "configuration": {"availableAgentIds": []},
    }


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


def test_obsolete_placeholder_models_endpoint_is_not_exposed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "no-models-router.db"))
    with TestClient(app) as client:
        assert client.get("/models/").status_code == 404


def test_session_creation_prepares_a_default_isolated_workspace(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sessions.db"
    monkeypatch.setattr(settings, "db_path", str(database_path))
    project = tmp_path / "project"
    project.mkdir()
    with TestClient(app) as client:
        response = client.post("/sessions/", json=_configured_session_payload(
            client, projectPath=str(project), goal="Write a test",
        ))

    assert response.status_code == 200
    with sqlite3.connect(database_path) as database:
        workspace = database.execute("SELECT mode, root_path FROM workspaces WHERE session_id = ?", (response.json()["id"],)).fetchone()
        session_path = database.execute("SELECT project_path FROM sessions WHERE id = ?", (response.json()["id"],)).fetchone()
    assert workspace is not None and workspace[0] == "snapshot"
    assert session_path is not None and session_path[0] == workspace[1]
    assert Path(workspace[1]).is_dir() and Path(workspace[1]) != project


def test_session_shell_resources_return_original_project_metadata(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "shell.db"
    monkeypatch.setattr(settings, "db_path", str(database_path))
    project = tmp_path / "project"
    project.mkdir()
    with TestClient(app) as client:
        registered = client.post("/projects/", json={"path": str(project), "displayName": "Argus UI"})
        created = client.post("/sessions/", json=_configured_session_payload(
            client, projectId=registered.json()["id"], goal="Polish the navigation",
        ))
        listed = client.get("/sessions/")
        detail = client.get(f"/sessions/{created.json()['id']}")

    assert listed.status_code == 200
    assert listed.json() == [{
        "id": created.json()["id"],
        "name": created.json()["name"],
        "projectId": registered.json()["id"],
        "projectDisplayName": "Argus UI",
        "originalProjectPath": str(project.resolve()),
        "goal": "Polish the navigation",
        "status": "setup",
        "startedAtMs": listed.json()[0]["startedAtMs"],
        "updatedAtMs": listed.json()[0]["updatedAtMs"],
        "completedAtMs": None,
    }]
    assert detail.status_code == 200
    assert detail.json()["originalProjectPath"] == str(project.resolve())
    assert detail.json()["projectDisplayName"] == "Argus UI"
    assert Path(detail.json()["workspacePath"]) != project.resolve()


def test_session_detail_returns_not_found_for_an_unknown_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "missing-session.db"))
    with TestClient(app) as client:
        response = client.get("/sessions/missing")
    assert response.status_code == 404


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
            **_configured_session_payload(client, projectPath=str(project), goal="Change in place"),
            "workspaceMode": "direct_write", "acknowledgeDirectWrite": True,
        })

    assert denied.status_code == 422
    assert accepted.status_code == 200
    with sqlite3.connect(database_path) as database:
        mode = database.execute("SELECT mode FROM workspaces WHERE session_id = ?", (accepted.json()["id"],)).fetchone()
    assert mode == ("direct_write",)


def test_session_creation_rejects_builtin_or_unknown_provider_bindings_before_workspace_setup(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "provider-required.db"
    monkeypatch.setattr(settings, "db_path", str(database_path))
    project = tmp_path / "project"
    project.mkdir()
    with TestClient(app) as client:
        builtin = client.post("/sessions/", json={
            "projectPath": str(project), "goal": "Do real work", "agents": [],
        })
        unknown = client.post("/sessions/", json={
            "projectPath": str(project), "goal": "Do real work", "coordinatorAgentId": "coordinator",
            "agents": [{"id": "coordinator", "role": "coordinator", "modelBinding": {"providerProfileId": "prv_missing", "modelId": "model-1"}}],
            "configuration": {"availableAgentIds": []},
        })

    assert builtin.status_code == 422
    assert builtin.json()["detail"]["code"] == "provider_model_required"
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "provider_profile_not_configured"
    with sqlite3.connect(database_path) as database:
        assert database.execute("SELECT COUNT(*) FROM workspaces").fetchone() == (0,)
