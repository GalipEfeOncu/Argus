"""Phase 7.1 localhost authentication and origin-boundary regressions."""

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from app.config import settings
from app.main import app


def test_http_runtime_rejects_missing_token_and_unexpected_origin(monkeypatch) -> None:
    monkeypatch.setattr(settings, "access_token", "process-secret")
    monkeypatch.setattr(settings, "allowed_origins", "tauri://localhost")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 401
        assert client.get(
            "/health",
            headers={"Authorization": "Bearer process-secret", "Origin": "https://unexpected.invalid"},
        ).status_code == 403
        response = client.get(
            "/health",
            headers={"Authorization": "Bearer process-secret", "Origin": "tauri://localhost"},
        )
        assert response.status_code == 200
        preflight = client.options(
            "/health",
            headers={
                "Origin": "tauri://localhost",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "tauri://localhost"


def test_websocket_rejects_other_local_process_and_unexpected_origin(monkeypatch) -> None:
    monkeypatch.setattr(settings, "access_token", "process-secret")
    monkeypatch.setattr(settings, "allowed_origins", "tauri://localhost")
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/sessions/missing", subprotocols=["argus.v1", "argus.token.wrong"]):
                pass
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws/sessions/missing",
                headers={"origin": "https://unexpected.invalid"},
                subprotocols=["argus.v1", "argus.token.process-secret"],
            ):
                pass
        with client.websocket_connect(
            "/ws/sessions/missing",
            headers={"origin": "tauri://localhost"},
            subprotocols=["argus.v1", "argus.token.process-secret"],
        ) as socket:
            assert socket.accepted_subprotocol == "argus.v1"
            closed = socket.receive()
            assert closed["type"] == "websocket.close"
            assert closed["reason"] == "Session not found"
