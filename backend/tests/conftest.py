from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from app.config import settings
from app.db.database import init_db
from tests.helpers.fakes import FakeClock, FakeIdGenerator, FakeProvider


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_id_generator() -> FakeIdGenerator:
    return FakeIdGenerator()


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider(("scripted provider response",))


@pytest_asyncio.fixture
async def temporary_sqlite_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Path]:
    """Initialize an isolated database without accessing the user's Argus data."""

    database_path = tmp_path / "argus-test.db"
    monkeypatch.setattr(settings, "db_path", str(database_path))
    await init_db()
    yield database_path
