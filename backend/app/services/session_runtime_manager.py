"""Process-owned lifecycle for provider-backed Coordinator turns."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from hashlib import sha256
import json
import uuid

import aiosqlite

from app.db.database import get_db, transaction
from app.db.repositories import EventRepository, StoredEvent, _now_ms, _safe_json
from app.providers.protocol import Cancelled, Finished, Provider, ProviderRequest, RetryableError, TerminalError, TextDelta, Usage
from app.services.budget_counter_service import BudgetCounterService
from app.schemas.coordinator_actions import (
    AskUserAction,
    AssignmentsAction,
    FinalAction,
    PartialAction,
    StopAction,
    WaitAction,
    coordinator_action_schema,
)
from app.services.assignment_scheduler import AssignmentScheduler, SchedulerRejected
from app.services.coordinator_cycle import CoordinatorCycle, CoordinatorCycleResult
from app.services.provider_profile_service import ProviderProfileService
from app.services.session_configuration_service import SessionConfigurationService


ProviderResolver = Callable[[str, str], Awaitable[Provider]]
EventPublisher = Callable[[str, list[dict]], Awaitable[None]]


class SessionRuntimeManager:
    """Own one idempotent background Coordinator turn per live session."""

    def __init__(
        self, *, provider_resolver: ProviderResolver | None = None,
        publisher: EventPublisher | None = None,
    ) -> None:
        self._provider_resolver = provider_resolver
        self._publisher = publisher
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._active_chat_streams: dict[str, tuple[Provider, str]] = {}
        self._lock = asyncio.Lock()
        self._shutting_down = False

    async def start(self, session_id: str) -> bool:
        async with self._lock:
            active = self._tasks.get(session_id)
            if self._shutting_down or (active is not None and not active.done()):
                return False
            task = asyncio.create_task(self._run(session_id), name=f"argus-coordinator-{session_id}")
            self._tasks[session_id] = task
            task.add_done_callback(lambda completed, value=session_id: self._discard(value, completed))
            return True

    async def wait(self, session_id: str) -> None:
        async with self._lock:
            task = self._tasks.get(session_id)
        if task is not None:
            await asyncio.shield(task)

    async def interrupt(self, session_id: str) -> bool:
        """Interrupt an active direct-chat provider response, if present."""

        active = self._active_chat_streams.get(session_id)
        if active is None:
            return False
        provider, request_id = active
        await provider.cancel(request_id)
        return True

    async def shutdown(self, timeout_seconds: float = 2.0) -> None:
        async with self._lock:
            self._shutting_down = True
            tasks = tuple(task for task in self._tasks.values() if not task.done())
        for session_id in tuple(self._tasks):
            await CoordinatorCycle.supersede_active(session_id)
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=max(0.0, timeout_seconds))
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.exception() if not task.cancelled() else None
        async with self._lock:
            self._tasks.clear()
            self._shutting_down = False

    async def recover_after_restart(self) -> int:
        """Fail an interrupted Coordinator provider turn without replaying it."""

        db = await get_db()
        try:
            async with db.execute(
                """SELECT DISTINCT session.id FROM sessions session
                   JOIN provider_operations operation ON operation.session_id = session.id
                   WHERE session.status IN ('preparing', 'running')
                     AND operation.operation_kind IN ('coordinator', 'chat')
                     AND operation.state = 'outcome_unknown'"""
            ) as cursor:
                session_ids = [str(row["id"]) for row in await cursor.fetchall()]
            for session_id in session_ids:
                await self._terminal_error(
                    db, session_id, "coordinator_restart_interrupted",
                    "The provider response was interrupted by a runtime restart and was not replayed.",
                    expected={"preparing", "running"},
                )
            return len(session_ids)
        finally:
            await db.close()

    def _discard(self, session_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(session_id) is task:
            self._tasks.pop(session_id, None)
        if not task.cancelled():
            task.exception()

    async def _run(self, session_id: str, specialist_context: str | None = None, cycle_depth: int = 0) -> None:
        db = await get_db()
        try:
            if cycle_depth >= 8:
                await self._terminal_error(
                    db, session_id, "coordinator_cycle_limit",
                    "The Coordinator reached the bounded specialist follow-up limit.", expected={"running"},
                )
                return
            try:
                context = await self._context(db, session_id)
            except Exception:
                await self._terminal_error(
                    db, session_id, "coordinator_configuration_invalid",
                    "The immutable Coordinator configuration could not be loaded.",
                    expected={"preparing", "running"},
                )
                return
            if context is None:
                return
            goal, coordinator_id, profile_id, model_id, system_prompt, participant_context, initial_status, session_type = context
            if session_type == "chat":
                await self._run_direct_chat(db, session_id, profile_id, model_id, system_prompt)
                return
            try:
                provider = await self._resolve_provider(db, profile_id, model_id)
            except Exception:
                await self._terminal_error(
                    db, session_id, "coordinator_provider_unavailable",
                    "The configured Coordinator provider is unavailable. Check its credential and installed provider support.",
                    expected={initial_status},
                )
                return
            if initial_status == "preparing":
                running = await self._commit(
                    db, session_id, {"preparing"}, [(
                        "session.status_changed", "system",
                        {"status": "running", "reasonSummary": "The configured Coordinator is ready."},
                    )],
                )
                await self._publish(session_id, running)
                if not running:
                    return
            request = ProviderRequest(
                request_id=f"coordinator_{uuid.uuid4().hex}", model_id=model_id,
                messages=(
                    {"role": "system", "content": f"{system_prompt}\nAvailable specialist snapshots: {participant_context}"},
                    {"role": "user", "content": goal},
                    *(await self._recent_human_messages(db, session_id)),
                    *(({"role": "user", "content": specialist_context},) if specialist_context else ()),
                ),
                response_schema=coordinator_action_schema(),
                metadata={"sessionId": session_id, "participantId": coordinator_id},
            )
            try:
                result = await CoordinatorCycle(db).execute(session_id, provider, request, apply_actions=False)
                await self._apply_result(db, session_id, coordinator_id, result, cycle_depth=cycle_depth)
            except asyncio.CancelledError:
                await provider.cancel(request.request_id)
                raise
            except Exception:
                await self._terminal_error(
                    db, session_id, "coordinator_runtime_failed",
                    "The Coordinator could not complete its turn.", expected={"running"},
                )
        finally:
            await db.close()

    async def _context(self, db: aiosqlite.Connection, session_id: str) -> tuple[str, str, str, str, str, str, str, str] | None:
        async with db.execute("SELECT COALESCE(goal, task) AS goal, status, session_type FROM sessions WHERE id = ?", (session_id,)) as cursor:
            session = await cursor.fetchone()
        if session is None or session["status"] not in {"preparing", "running"}:
            return None
        async with db.execute(
            "SELECT id, snapshot_json FROM session_agents WHERE session_id = ? AND role = 'coordinator' ORDER BY created_at_ms LIMIT 1",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            await self._terminal_error(db, session_id, "coordinator_configuration_missing", "The session has no Coordinator configuration.", expected={str(session["status"])})
            return None
        snapshot = json.loads(row["snapshot_json"])
        binding = snapshot.get("modelBinding")
        if not isinstance(binding, dict) or binding.get("providerProfileId") == "builtin":
            await self._terminal_error(db, session_id, "coordinator_configuration_missing", "The Coordinator requires a configured provider and model.", expected={str(session["status"])})
            return None
        profile_id, model_id = binding.get("providerProfileId"), binding.get("modelId")
        if not isinstance(profile_id, str) or not isinstance(model_id, str):
            await self._terminal_error(db, session_id, "coordinator_configuration_missing", "The Coordinator requires a configured provider and model.", expected={str(session["status"])})
            return None
        prompt = snapshot.get("systemPrompt")
        if not isinstance(prompt, str) or not prompt.strip():
            prompt = "Return exactly one valid Coordinator action for the user's goal. Do not grant permissions or change policy."
        configuration = await SessionConfigurationService(db).current(session_id)
        available = set(configuration.available_agent_ids)
        participant_context = _safe_json([
            {"id": agent["id"], "role": agent["role"], "capabilities": agent["capabilities"], "toolAllowlist": agent["toolAllowlist"]}
            for agent in configuration.agent_snapshots if agent["id"] in available
        ])
        return str(session["goal"]), str(row["id"]), profile_id, model_id, prompt, participant_context, str(session["status"]), str(session["session_type"])

    async def _run_direct_chat(
        self, db: aiosqlite.Connection, session_id: str, profile_id: str, model_id: str, system_prompt: str,
    ) -> None:
        """Stream one ordinary provider response without workspace orchestration."""

        try:
            provider = await self._resolve_provider(db, profile_id, model_id)
        except Exception:
            await self._commit_chat_error(db, session_id, "chat_provider_unavailable", "The configured provider is unavailable. Check its credential and try again.")
            return

        request = ProviderRequest(
            request_id=f"chat_{uuid.uuid4().hex}", model_id=model_id,
            messages=(
                {"role": "system", "content": system_prompt},
                *(await self._recent_human_messages(db, session_id)),
            ),
            metadata={"sessionId": session_id, "participantId": "coordinator", "sessionType": "chat"},
        )
        operation_id = f"provider_{request.request_id}"
        fingerprint = sha256(f"{request.request_id}:{request.model_id}".encode()).hexdigest()
        audit_db = await get_db()
        try:
            async with transaction(audit_db):
                await audit_db.execute(
                    """INSERT INTO provider_operations (id, session_id, assignment_id, operation_kind, mutation_class,
                       state, request_fingerprint, started_at_ms) VALUES (?, ?, NULL, 'chat', 'read_only', 'running', ?, ?)""",
                    (operation_id, session_id, fingerprint, _now_ms()),
                )
        finally:
            await audit_db.close()

        message_id = f"msg_{uuid.uuid4().hex}"
        created = False
        finished = False
        cancelled = False
        outcome = "failed"
        self._active_chat_streams[session_id] = (provider, request.request_id)
        try:
            async for event in provider.stream(request):
                if isinstance(event, TextDelta) and event.text:
                    if not created:
                        committed = await self._commit(db, session_id, {"running"}, [(
                            "message.created", "coordinator", {
                                "messageId": message_id, "authorId": "coordinator", "authorKind": "coordinator",
                                "content": event.text[:64_000], "mentionIds": [], "streaming": True,
                            },
                        )])
                        await self._publish(session_id, committed)
                        created = bool(committed)
                    else:
                        committed = await self._commit(db, session_id, {"running"}, [(
                            "message.delta", "coordinator", {"messageId": message_id, "delta": event.text[:64_000]},
                        )])
                        await self._publish(session_id, committed)
                elif isinstance(event, Usage):
                    try:
                        before = await EventRepository(db).last_sequence(session_id)
                        await BudgetCounterService(db).record_coordinator_usage(
                            session_id, input_tokens=event.input_tokens or 0, output_tokens=event.output_tokens or 0,
                            normalized_cost=event.cost_usd, duration_ms=0,
                            cost_uncertainty="exact" if event.cost_usd is not None and event.exact else ("estimated" if event.cost_usd is not None else "unavailable"),
                            scope_id=request.request_id,
                        )
                        usage_page = await EventRepository(db).page_after(session_id, after_sequence=before)
                        await self._publish(session_id, list(usage_page.events))
                    except Exception:
                        await provider.cancel(request.request_id)
                        await self._commit_chat_error(db, session_id, "chat_usage_limit", "This chat reached its configured usage limit.", message_id if created else None)
                        return
                elif isinstance(event, (RetryableError, TerminalError)):
                    await self._commit_chat_error(db, session_id, event.code, event.summary, message_id if created else None)
                    return
                elif isinstance(event, Cancelled):
                    cancelled = True
                    break
                elif isinstance(event, Finished):
                    outcome = "succeeded"
                    finished = True
                    break
                await asyncio.sleep(0)
            if created and finished:
                completed = await self._commit(db, session_id, {"running"}, [(
                    "message.completed", "coordinator", {"messageId": message_id},
                )])
                await self._publish(session_id, completed)
            elif created and cancelled:
                completed = await self._commit(db, session_id, {"running"}, [(
                    "message.completed", "coordinator", {"messageId": message_id},
                )])
                await self._publish(session_id, completed)
            elif created:
                await self._commit_chat_error(db, session_id, "chat_incomplete_response", "The provider ended the response unexpectedly. Try again.", message_id)
            else:
                await self._commit_chat_error(db, session_id, "chat_empty_response", "The provider returned an empty response. Try again.")
        except asyncio.CancelledError:
            await provider.cancel(request.request_id)
            raise
        except Exception:
            await self._commit_chat_error(db, session_id, "chat_provider_error", "The provider could not complete this response. Try again.", message_id if created else None)
        finally:
            if self._active_chat_streams.get(session_id) == (provider, request.request_id):
                self._active_chat_streams.pop(session_id, None)
            audit_db = await get_db()
            try:
                async with transaction(audit_db):
                    await audit_db.execute(
                        "UPDATE provider_operations SET state = ?, completed_at_ms = ? WHERE id = ? AND state = 'running'",
                        (outcome, _now_ms(), operation_id),
                    )
            finally:
                await audit_db.close()

    async def _commit_chat_error(
        self, db: aiosqlite.Connection, session_id: str, code: str, summary: str, message_id: str | None = None,
    ) -> None:
        specs: list[tuple[str, str, dict]] = []
        if message_id is not None:
            specs.append(("message.completed", "coordinator", {"messageId": message_id}))
        specs.append((
            "error.created", "system", {"errorId": f"chat_{uuid.uuid4().hex}", "code": code, "summary": summary, "recoverable": True},
        ))
        events = await self._commit(db, session_id, {"running"}, specs)
        await self._publish(session_id, events)

    async def _resolve_provider(self, db: aiosqlite.Connection, profile_id: str, model_id: str) -> Provider:
        if self._provider_resolver is not None:
            return await self._provider_resolver(profile_id, model_id)
        return await ProviderProfileService(db).runtime_provider(profile_id, model_id)

    async def _recent_human_messages(
        self, db: aiosqlite.Connection, session_id: str,
    ) -> tuple[dict[str, str], ...]:
        async with db.execute(
            """SELECT payload_json FROM events WHERE session_id = ? AND event_type = 'message.created'
               AND actor_id = 'human' ORDER BY sequence DESC LIMIT 20""",
            (session_id,),
        ) as cursor:
            rows = list(reversed(await cursor.fetchall()))
        messages: list[dict[str, str]] = []
        for row in rows:
            content = json.loads(row["payload_json"]).get("content")
            if isinstance(content, str):
                messages.append({"role": "user", "content": content})
        return tuple(messages)

    async def _apply_result(
        self, db: aiosqlite.Connection, session_id: str, coordinator_id: str, result: CoordinatorCycleResult,
        *, cycle_depth: int = 0,
    ) -> None:
        action = result.action
        if action is None:
            if result.error_code == "user_superseded":
                return
            await self._terminal_error(
                db, session_id, result.error_code or "coordinator_action_invalid",
                result.error_summary or "The Coordinator returned no valid action.", expected={"running"},
            )
            return
        if isinstance(action, AssignmentsAction):
            if not await self._is_status(db, session_id, "running"):
                return
            if len(action.assignments) != 1:
                await self._terminal_error(
                    db, session_id, "specialist_batch_unsupported",
                    "This runtime executes one bounded specialist assignment per Coordinator turn.",
                    expected={"running"},
                )
                return
            assignment_ids: list[str] = []
            try:
                cycle = CoordinatorCycle(db)
                for proposal in action.assignments:
                    persisted = await cycle.persist_assignments(
                        session_id, action.model_copy(update={"assignments": [proposal]}), require_running=True,
                    )
                    assignment_ids.extend(persisted)
            except SchedulerRejected as error:
                unavailable = await self._fail_unavailable_assignments(db, session_id, tuple(assignment_ids))
                await self._publish(session_id, unavailable)
                if not unavailable:
                    await self._terminal_error(
                        db, session_id, error.code, error.summary, expected={"running"},
                    )
                return
            message = await self._message(db, session_id, coordinator_id, action.routing_summary, expected={"running"})
            await self._publish(session_id, message)
            async with db.execute(
                "SELECT COUNT(*) AS total FROM assignments WHERE session_id = ? AND id IN (%s) AND operation_class != 'read_only'" % ",".join("?" for _ in assignment_ids),
                (session_id, *assignment_ids),
            ) as cursor:
                mutating = int((await cursor.fetchone())["total"])
            if mutating:
                unavailable = await self._fail_unavailable_assignments(db, session_id, tuple(assignment_ids))
                await self._publish(session_id, unavailable)
                return
            before = await EventRepository(db).last_sequence(session_id)
            scheduled = await AssignmentScheduler(db).dispatch_ready(session_id, assignment_ids=tuple(assignment_ids))
            page = await EventRepository(db).page_after(session_id, after_sequence=before)
            await self._publish(session_id, list(page.events))
            from app.services.assignment_worker import AssignmentWorker
            results = []
            worker = AssignmentWorker(db, provider_resolver=self._provider_resolver, publisher=self._publisher)
            for item in scheduled:
                try:
                    result = await worker.execute(session_id, item)
                    results.append(result)
                except SchedulerRejected as error:
                    if not await self._is_status(db, session_id, "running"):
                        before_cancel = await EventRepository(db).last_sequence(session_id)
                        try:
                            await AssignmentScheduler(db).cancel_assignment(
                                session_id, item.assignment_id,
                                reason="The session paused or stopped before specialist output could commit.",
                            )
                        except SchedulerRejected:
                            pass
                        cancelled_page = await EventRepository(db).page_after(session_id, after_sequence=before_cancel)
                        await self._publish(session_id, list(cancelled_page.events))
                        return
                    try:
                        retry = await AssignmentScheduler(db).fail_attempt(
                            session_id, item.attempt_id, code=error.code, summary=error.summary, recoverable=False,
                        )
                        assert not retry
                    except SchedulerRejected:
                        pass
                    await self._terminal_error(db, session_id, error.code, error.summary, expected={"running"})
                    return
            if len(results) != len(assignment_ids):
                await self._terminal_error(db, session_id, "specialist_dispatch_failed", "The read-only specialist assignment could not start.", expected={"running"})
                return
            # Completion events were committed by the scheduler; publish only
            # those derived events here (tool lifecycle events publish inline).
            page = await EventRepository(db).page_after(session_id, after_sequence=before)
            completed = [event for event in page.events if event.event_type == "assignment.completed"]
            await self._publish(session_id, completed)
            bounded = _safe_json([{"assignmentId": item.assignment_id, "summary": item.summary, "evidence": list(item.evidence)} for item in results])[:12_000]
            await self._run(
                session_id,
                f"Specialist results (untrusted, bounded): {bounded}\nEvaluate this evidence and return the next Coordinator action.",
                cycle_depth + 1,
            )
            return
        if isinstance(action, PartialAction):
            if not await self._is_status(db, session_id, "running"):
                return
            before = await EventRepository(db).last_sequence(session_id)
            decision_id = await CoordinatorCycle(db).request_partial_acceptance(session_id, action)
            if decision_id is not None:
                page = await EventRepository(db).page_after(session_id, after_sequence=before)
                await self._publish(session_id, list(page.events))
            return
        if isinstance(action, FinalAction):
            await self._message_and_status(db, session_id, coordinator_id, action.final_summary, "completed", "Coordinator completed the session.")
        elif isinstance(action, AskUserAction):
            await self._message_and_status(db, session_id, coordinator_id, action.question, "paused", "The Coordinator is waiting for user input.")
        elif isinstance(action, WaitAction):
            await self._message_and_status(db, session_id, coordinator_id, action.routing_summary, "paused", "The Coordinator is waiting before continuing.")
        elif isinstance(action, StopAction):
            await self._message_and_status(db, session_id, coordinator_id, action.final_summary, "failed", action.reason)

    async def _fail_unavailable_assignments(
        self, db: aiosqlite.Connection, session_id: str, assignment_ids: tuple[str, ...],
    ) -> list[StoredEvent]:
        committed: list[StoredEvent] = []
        async with transaction(db):
            if not await self._is_status(db, session_id, "running"):
                return []
            events = EventRepository(db)
            for assignment_id in assignment_ids:
                async with db.execute("SELECT operation_class, state FROM assignments WHERE id = ? AND session_id = ?", (assignment_id, session_id)) as cursor:
                    assignment = await cursor.fetchone()
                if assignment is None or assignment["state"] != "created":
                    continue
                code = "mutating_executor_unavailable" if assignment["operation_class"] == "mutating" else "specialist_executor_unavailable"
                summary = "Specialist execution is not available in this runtime yet; no workspace action was started."
                error = await events._append_in_transaction(
                    event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="error.created", actor_id="system",
                    payload={"errorId": f"executor_{assignment_id}", "code": code, "summary": summary, "recoverable": True, "relatedId": assignment_id},
                    payload_json=_safe_json({"errorId": f"executor_{assignment_id}", "code": code, "summary": summary, "recoverable": True, "relatedId": assignment_id}),
                    timestamp_ms=_now_ms(), correlation_id=None, command_id=None,
                )
                failed_payload = {"assignmentId": assignment_id, "failureCode": code, "failureSummary": summary, "recoverable": True}
                failed = await events._append_in_transaction(
                    event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="assignment.failed", actor_id="system",
                    payload=failed_payload, payload_json=_safe_json(failed_payload), timestamp_ms=_now_ms(), correlation_id=None, command_id=None,
                )
                await db.execute("UPDATE assignments SET state = 'failed', terminal_event_id = ?, updated_at_ms = ? WHERE id = ?", (failed.event_id, _now_ms(), assignment_id))
                committed.extend((error, failed))
            if committed:
                status_payload = {"status": "failed", "reasonSummary": "Specialist execution is not available; no assignment was left running."}
                committed.append(await events._append_in_transaction(
                    event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="session.status_changed", actor_id="system",
                    payload=status_payload, payload_json=_safe_json(status_payload), timestamp_ms=_now_ms(), correlation_id=None, command_id=None,
                ))
        return committed

    async def _message_and_status(
        self, db: aiosqlite.Connection, session_id: str, coordinator_id: str,
        content: str, status: str, reason: str,
    ) -> None:
        events = await self._commit(db, session_id, {"running"}, [
            ("message.created", "coordinator", {"messageId": f"msg_{uuid.uuid4().hex}", "authorId": coordinator_id, "authorKind": "coordinator", "content": content, "mentionIds": [], "streaming": False}),
            ("session.status_changed", "system", {"status": status, "reasonSummary": reason}),
        ])
        await self._publish(session_id, events)

    async def _message(
        self, db: aiosqlite.Connection, session_id: str, coordinator_id: str, content: str, *, expected: set[str],
    ) -> list[StoredEvent]:
        return await self._commit(db, session_id, expected, [
            ("message.created", "coordinator", {"messageId": f"msg_{uuid.uuid4().hex}", "authorId": coordinator_id, "authorKind": "coordinator", "content": content, "mentionIds": [], "streaming": False}),
        ])

    async def _terminal_error(
        self, db: aiosqlite.Connection, session_id: str, code: str, summary: str, *, expected: set[str],
    ) -> None:
        safe_summary = summary[:800]
        events = await self._commit(db, session_id, expected, [
            ("error.created", "system", {"errorId": f"runtime_{uuid.uuid4().hex}", "code": code, "summary": safe_summary, "recoverable": True}),
            ("session.status_changed", "system", {"status": "failed", "reasonSummary": "The Coordinator runtime stopped safely."}),
        ])
        await self._publish(session_id, events)

    async def _commit(
        self, db: aiosqlite.Connection, session_id: str, expected: set[str],
        specs: list[tuple[str, str, dict]],
    ) -> list[StoredEvent]:
        committed: list[StoredEvent] = []
        async with transaction(db):
            async with db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)) as cursor:
                session = await cursor.fetchone()
            if session is None or session["status"] not in expected:
                return []
            repository = EventRepository(db)
            for event_type, actor_id, payload in specs:
                committed.append(await repository._append_in_transaction(
                    event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type=event_type, actor_id=actor_id,
                    payload=payload, payload_json=_safe_json(payload), timestamp_ms=_now_ms(), correlation_id=None, command_id=None,
                ))
        return committed

    async def _is_status(self, db: aiosqlite.Connection, session_id: str, status: str) -> bool:
        async with db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)) as cursor:
            row = await cursor.fetchone()
        return row is not None and row["status"] == status

    async def _publish(self, session_id: str, events: list[StoredEvent]) -> None:
        if not events:
            return
        from app.services.command_processor import event_wire_value
        values = [event_wire_value(event) for event in events]
        if self._publisher is not None:
            await self._publisher(session_id, values)
            return
        from app.api.websocket import connection_hub
        await connection_hub.publish(session_id, values)

session_runtime_manager = SessionRuntimeManager()
