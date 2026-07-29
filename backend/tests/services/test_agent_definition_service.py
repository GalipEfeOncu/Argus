"""Phase 5.1 coverage for immutable definitions and capability/evidence routing."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _custom_definition(name: str = "Accessibility specialist") -> dict[str, object]:
    return {
        "name": name,
        "kind": "custom",
        "role": "accessibility_specialist",
        "systemPrompt": "Inspect UI changes and return structured accessibility evidence.",
        "modelBinding": {"providerProfileId": "builtin", "modelId": "provider-neutral"},
        "capabilities": ["workspace.read"],
        "skillIds": [],
        "toolAllowlist": ["read_file", "search_files"],
        "permissionProfile": "balanced",
        "evidenceKinds": ["accessibility_review"],
        "evidenceSchema": {
            "type": "object",
            "required": ["verdict"],
            "properties": {"verdict": {"type": "string", "enum": ["approved", "needs_changes"]}},
            "additionalProperties": False,
        },
        "outputLanguage": "tr",
    }


def test_definitions_seed_all_builtin_templates_and_custom_snapshots_do_not_drift(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "definitions.db"))
    project = tmp_path / "project"
    project.mkdir()
    with TestClient(app) as client:
        builtins = client.get("/agent-definitions/")
        created = client.post("/agent-definitions/", json=_custom_definition())
        definition_id = created.json()["id"]
        session = client.post("/sessions/", json={
            "projectPath": str(project), "goal": "Review the interface",
            "agents": [
                {"id": "coord", "role": "coordinator"},
                {"id": "a11y", "role": "accessibility_specialist", "agentDefinitionId": definition_id},
            ],
            "coordinatorAgentId": "coord",
            "configuration": {
                "availableAgentIds": ["a11y"],
                "requiredRoleRules": [{
                    "id": "a11y_gate", "role": "accessibility_specialist", "applicability": "always",
                    "successEvidence": "accessibility_review", "minimumCompletions": 1,
                    "requiredCapabilities": ["workspace.read"],
                }],
            },
        })
        later_version = client.post("/agent-definitions/", json=_custom_definition("Accessibility specialist v2"))
        snapshot = client.get(f"/sessions/{session.json()['id']}/configuration")

    assert builtins.status_code == 200
    assert {item["role"] for item in builtins.json() if item["kind"] == "builtin"} == {
        "coordinator", "planner", "builder", "reviewer", "tester", "ui_agent",
    }
    assert created.status_code == 201 and later_version.status_code == 201
    assert session.status_code == 200
    custom_snapshot = next(item for item in snapshot.json()["agentSnapshots"] if item["sourceAgentId"] == "a11y")
    assert custom_snapshot["agentDefinitionId"] == definition_id
    assert custom_snapshot["skillIds"] == []
    assert custom_snapshot["evidenceKinds"] == ["accessibility_review"]
    assert custom_snapshot["outputLanguage"] == "tr"


def test_session_override_cannot_expand_definition_capabilities(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "definitions-escalation.db"))
    project = tmp_path / "project"
    project.mkdir()
    with TestClient(app) as client:
        definition = client.post("/agent-definitions/", json=_custom_definition()).json()
        response = client.post("/sessions/", json={
            "projectPath": str(project), "goal": "Review safely",
            "agents": [
                {"id": "coord", "role": "coordinator"},
                {
                    "id": "a11y", "role": "accessibility_specialist", "agentDefinitionId": definition["id"],
                    "capabilities": ["workspace.read", "workspace.write"],
                },
            ],
            "coordinatorAgentId": "coord",
        })

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "agent_override_escalation"


def test_custom_roles_cannot_replace_builtin_evidence_or_lose_their_own_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "definitions-evidence.db"))
    with TestClient(app) as client:
        missing = client.post("/agent-definitions/", json={**_custom_definition(), "evidenceKinds": []})
        reserved = client.post("/agent-definitions/", json={**_custom_definition(), "evidenceKinds": ["approved_review"]})

    assert missing.status_code == 422 and missing.json()["detail"]["code"] == "custom_evidence_kind_required"
    assert reserved.status_code == 422 and reserved.json()["detail"]["code"] == "reserved_evidence_kind"


def test_legacy_model_snapshot_is_translated_to_the_new_non_secret_binding(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "definitions-legacy.db"))
    project = tmp_path / "project"
    project.mkdir()
    with TestClient(app) as client:
        response = client.post("/sessions/", json={
            "projectPath": str(project), "goal": "Keep compatibility",
            "roleConfigs": [{"role": "builder", "providerId": "local", "modelId": "test-model"}],
        })

    assert response.status_code == 200
