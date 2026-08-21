from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_local_profile_api_create_read_update_and_validation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "profile.db"))
    with TestClient(app) as client:
        empty = client.get("/profile")
        missing_name = client.patch("/profile", json={"bio": "Local only"})
        unknown_field = client.patch("/profile", json={"displayName": "Ada", "token": "no"})
        created = client.patch("/profile", json={"displayName": "  Ada  ", "bio": "  Builder  "})
        read = client.get("/profile")
        no_op = client.patch("/profile", json={"displayName": "Ada"})
        cleared = client.patch("/profile", json={"bio": None})

    assert empty.status_code == 200 and empty.json() == {"profile": None}
    assert missing_name.status_code == 422
    assert missing_name.json()["detail"]["code"] == "display_name_required"
    assert unknown_field.status_code == 422
    assert created.status_code == 200
    assert created.json()["displayName"] == "Ada"
    assert created.json()["bio"] == "Builder"
    assert read.json()["profile"] == created.json()
    assert no_op.json()["updatedAtMs"] == created.json()["updatedAtMs"]
    assert cleared.json()["bio"] is None
    assert set(cleared.json()) == {"displayName", "bio", "createdAtMs", "updatedAtMs"}
