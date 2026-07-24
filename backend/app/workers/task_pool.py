"""In-process bounded worker tasks for the single Argus sidecar."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.providers.protocol import Cancelled, Provider, ProviderEvent, ProviderRequest
from app.workers.context import ContextSelectionMetadata

EventSink = Callable[[ProviderEvent], Awaitable[None]]
ContextMetadataSink = Callable[[ContextSelectionMetadata], Awaitable[None]]


class TaskWorkerPool:
    """Runs bounded async worker tasks; it never spawns a Python runtime per agent."""

    def __init__(self, max_workers: int = 3) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least one")
        self._capacity = asyncio.Semaphore(max_workers)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._sinks: dict[str, EventSink] = {}
        self._cancelled_notified: set[str] = set()

    @property
    def active_request_ids(self) -> tuple[str, ...]:
        return tuple(self._tasks)

    def submit(
        self,
        provider: Provider,
        request: ProviderRequest,
        sink: EventSink,
        *,
        context_metadata: ContextSelectionMetadata | None = None,
        context_metadata_sink: ContextMetadataSink | None = None,
    ) -> asyncio.Task[None]:
        if request.request_id in self._tasks:
            raise ValueError(f"request '{request.request_id}' is already running")
        task = asyncio.create_task(
            self._run(provider, request, sink, context_metadata, context_metadata_sink),
            name=f"argus-worker-{request.request_id}",
        )
        self._tasks[request.request_id] = task
        self._sinks[request.request_id] = sink
        task.add_done_callback(lambda _: self._cleanup(request.request_id))
        return task

    async def cancel(self, provider: Provider, request_id: str) -> bool:
        task = self._tasks.get(request_id)
        if task is None:
            return False
        try:
            await provider.cancel(request_id)
        finally:
            self._cancelled_notified.add(request_id)
            task.cancel()
            try:
                await self._sinks[request_id](Cancelled())
            except Exception:
                # A disconnected event consumer must never keep provider work alive.
                pass
        return True

    async def _run(
        self,
        provider: Provider,
        request: ProviderRequest,
        sink: EventSink,
        context_metadata: ContextSelectionMetadata | None,
        context_metadata_sink: ContextMetadataSink | None,
    ) -> None:
        try:
            async with self._capacity:
                try:
                    if context_metadata is not None and context_metadata_sink is not None:
                        await context_metadata_sink(context_metadata)
                    async for event in provider.stream(request):
                        await sink(event)
                except asyncio.CancelledError:
                    if request.request_id not in self._cancelled_notified:
                        self._cancelled_notified.add(request.request_id)
                        await sink(Cancelled())
                    raise
        finally:
            self._cleanup(request.request_id)

    def _cleanup(self, request_id: str) -> None:
        self._tasks.pop(request_id, None)
        self._sinks.pop(request_id, None)
        self._cancelled_notified.discard(request_id)
