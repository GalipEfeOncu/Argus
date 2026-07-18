import aiosqlite
import pytest

from app.config import settings
from app.db.database import get_db
from tests.helpers.fakes import FakeClock, FakeIdGenerator, FakeProvider


@pytest.mark.asyncio
async def test_temporary_sqlite_database_is_isolated(temporary_sqlite_db) -> None:
    assert settings.db_path == str(temporary_sqlite_db)
    assert temporary_sqlite_db.exists()

    database = await get_db()
    try:
        await database.execute(
            "INSERT INTO sessions (id, name, project_path, task, role_configs, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("session_test", "Test", "workspace", "task", "[]", 0),
        )
        await database.commit()
        async with database.execute("SELECT COUNT(*) AS total FROM sessions") as cursor:
            row = await cursor.fetchone()
    finally:
        await database.close()

    assert row["total"] == 1

    unrelated_database = temporary_sqlite_db.with_name("unrelated.db")
    async with aiosqlite.connect(unrelated_database) as database:
        async with database.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sessions'"
        ) as cursor:
            assert await cursor.fetchone() is None


@pytest.mark.asyncio
async def test_deterministic_fakes_do_not_use_network_or_global_time(
    fake_clock: FakeClock,
    fake_id_generator: FakeIdGenerator,
    fake_provider: FakeProvider,
) -> None:
    assert fake_clock.timestamp() == 1_767_225_600
    assert fake_clock.advance(2.5).isoformat() == "2026-01-01T00:00:02.500000+00:00"
    assert [fake_id_generator.next(), fake_id_generator.next()] == ["test_0001", "test_0002"]
    assert await fake_provider.complete("summarize the test") == "scripted provider response"
    assert fake_provider.prompts == ["summarize the test"]
