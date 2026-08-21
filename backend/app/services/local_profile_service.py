"""Transactional persistence for the singleton non-secret local profile."""

from __future__ import annotations

import aiosqlite

from app.db.database import transaction
from app.db.repositories import _now_ms
from app.schemas.local_profile import LocalProfilePatch, LocalProfileResponse, LocalProfileStateResponse


class LocalProfileError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class LocalProfileService:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def get(self) -> LocalProfileStateResponse:
        row = await self._row()
        return LocalProfileStateResponse(profile=None if row is None else self._response(row))

    async def patch(self, value: LocalProfilePatch) -> LocalProfileResponse:
        async with transaction(self._db):
            row = await self._row()
            supplied = value.model_fields_set
            if row is None:
                if "display_name" not in supplied:
                    raise LocalProfileError(
                        "display_name_required",
                        "A display name is required when creating the local profile.",
                    )
                now = _now_ms()
                await self._db.execute(
                    """INSERT INTO local_profile (id, display_name, bio, created_at_ms, updated_at_ms)
                       VALUES ('local', ?, ?, ?, ?)""",
                    (value.display_name, value.bio if "bio" in supplied else None, now, now),
                )
                created = await self._row()
                assert created is not None
                return self._response(created)

            display_name = value.display_name if "display_name" in supplied else row["display_name"]
            bio = value.bio if "bio" in supplied else row["bio"]
            if display_name == row["display_name"] and bio == row["bio"]:
                return self._response(row)

            updated_at_ms = max(_now_ms(), int(row["updated_at_ms"]) + 1)
            await self._db.execute(
                "UPDATE local_profile SET display_name = ?, bio = ?, updated_at_ms = ? WHERE id = 'local'",
                (display_name, bio, updated_at_ms),
            )
            updated = await self._row()
            assert updated is not None
            return self._response(updated)

    async def _row(self) -> aiosqlite.Row | None:
        async with self._db.execute("SELECT * FROM local_profile WHERE id = 'local'") as cursor:
            return await cursor.fetchone()

    @staticmethod
    def _response(row: aiosqlite.Row) -> LocalProfileResponse:
        return LocalProfileResponse.model_validate({
            "displayName": row["display_name"],
            "bio": row["bio"],
            "createdAtMs": row["created_at_ms"],
            "updatedAtMs": row["updated_at_ms"],
        })
