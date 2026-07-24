"""Bridge safe context metadata into durable assignment-attempt records."""

from __future__ import annotations

import aiosqlite

from app.db.repositories import AssignmentAttemptRepository
from app.workers.context import ContextSelectionMetadata


class AssignmentAttemptContextRecorder:
    """Records selection metadata only; prompt text never crosses this boundary."""

    def __init__(self, db: aiosqlite.Connection, attempt_id: str) -> None:
        self._repository = AssignmentAttemptRepository(db)
        self._attempt_id = attempt_id

    async def record(self, metadata: ContextSelectionMetadata) -> None:
        await self._repository.record_context_selection(self._attempt_id, metadata.persistence_value())
