"""In-process fencing for a session workspace mutation and cancellation."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from collections.abc import AsyncIterator


class SessionMutationFence:
    """Serialize a committed cancellation with an in-flight workspace write.

    SQLite remains authoritative for the resulting assignment state.  This
    short-lived fence only closes the gap between checking that a worker still
    owns its lease and performing the actual filesystem mutation.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    @asynccontextmanager
    async def mutation(self, session_id: str) -> AsyncIterator[None]:
        async with self._lock(session_id):
            yield

    async def wait_for_mutations(self, session_id: str) -> None:
        """Wait for any already-started write before committing cancellation."""

        async with self._lock(session_id):
            return


session_mutation_fence = SessionMutationFence()
