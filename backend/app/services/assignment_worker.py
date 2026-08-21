"""Bounded provider-backed execution for read-only specialist assignments."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import json
from pathlib import Path
import time
import uuid
from typing import Any

import aiosqlite

from app.db.database import transaction
from app.config import settings
from app.db.repositories import EventRepository, StoredEvent, _now_ms, _safe_json
from app.providers.protocol import (
    AssistantMessage, Cancelled, Provider, ProviderRequest, RetryableError,
    StructuredOutput, TerminalError, TextDelta, ToolCall, ToolMessage, Usage,
)
from app.schemas.session_events import Evidence
from app.services.assignment_scheduler import AssignmentScheduler, ScheduledAssignment, SchedulerRejected
from app.services.provider_profile_service import ProviderProfileService
from app.services.session_configuration_service import SessionConfigurationService
from app.services.workspace_service import ProjectWorkspaceService, ScopedToolService, WorkspaceError
from app.workers.context import AgentSnapshot, AssignmentContext, AssignmentContextBuilder, _redact


READ_TOOLS = frozenset({"read_file", "list_dir", "search_files"})
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "read_file": {"name": "read_file", "description": "Read one UTF-8 file in the session workspace.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    "list_dir": {"name": "list_dir", "description": "List a directory in the session workspace.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "additionalProperties": False}},
    "search_files": {"name": "search_files", "description": "Search literal text in workspace files.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "path": {"type": "string"}}, "required": ["query"], "additionalProperties": False}},
}


@dataclass(frozen=True)
class SpecialistResult:
    assignment_id: str
    summary: str
    evidence: tuple[dict[str, Any], ...]


class AssignmentWorker:
    """Execute one scheduled read-only assignment without mutation authority."""

    def __init__(self, db: aiosqlite.Connection, *, provider_resolver=None, publisher=None) -> None:
        self._db = db
        self._provider_resolver = provider_resolver
        self._publisher = publisher

    async def execute(self, session_id: str, scheduled: ScheduledAssignment) -> SpecialistResult:
        assignment, proposal, raw_agent, goal, limits = await self._context(session_id, scheduled)
        if scheduled.operation_class != "read_only":
            raise SchedulerRejected("mutating_specialist_denied", "Mutating specialist execution is not available; no workspace write was started.")
        requested_tools = proposal.get("requestedTools", [])
        capabilities = set(proposal.get("requestedCapabilities", []))
        allowlist = set(raw_agent.get("toolAllowlist", []))
        tools = set(requested_tools) & allowlist & READ_TOOLS
        if "workspace.read" not in capabilities or set(requested_tools) != tools:
            raise SchedulerRejected("specialist_tool_denied", "The assignment's read tools are outside its immutable capability or allowlist.")
        configuration = await SessionConfigurationService(self._db).current(session_id)
        from app.services.approval_grant_service import ApprovalGrantService
        authority = await ApprovalGrantService(self._db).evaluate_snapshot(
            session_id, configuration, capability="workspace.read", scope_path=".",
            operation_class="read_only", consume_once=False,
        )
        if authority.outcome != "allow":
            raise SchedulerRejected("specialist_authority_expired", "Read-only workspace authority is no longer active.")
        configured_iterations = limits.get("maxModelIterationsPerAssignment")
        max_iterations = 8 if configured_iterations is None else max(0, min(int(configured_iterations), 20))
        configured_calls = limits.get("maxToolCallsPerAssignment")
        max_calls = 20 if configured_calls is None else max(0, min(int(configured_calls), 100))
        configured_wall_clock = limits.get("maxWallClockSeconds")
        wall_clock = 120 if configured_wall_clock is None else max(0, min(int(configured_wall_clock), 600))
        if max_iterations == 0:
            raise SchedulerRejected("specialist_iteration_limit", "The specialist model-iteration limit is zero.")
        if wall_clock == 0:
            raise SchedulerRejected("specialist_wall_clock_limit", "The specialist wall-clock limit is zero.")
        binding = raw_agent.get("modelBinding")
        if not isinstance(binding, dict) or binding.get("providerProfileId") in {None, "builtin"} or not isinstance(binding.get("modelId"), str):
            raise SchedulerRejected("specialist_provider_missing", "The specialist requires an explicitly configured provider and model.")
        provider = await self._resolve(str(binding["providerProfileId"]), str(binding["modelId"]))
        built = AssignmentContextBuilder().build(
            agent=AgentSnapshot(
                agent_id=str(assignment["assignee_session_agent_id"]), role=str(raw_agent.get("role", "agent")),
                system_prompt=str(raw_agent.get("systemPrompt", "Complete the bounded assignment.")),
                definition_version=str(raw_agent.get("definitionVersion", "snapshot")),
                enabled_skills=tuple(str(item) for item in raw_agent.get("skillIds", [])),
                tool_allowlist=tuple(sorted(tools)), permission_profile=str(raw_agent.get("permissionProfile", "balanced")),
                output_language=raw_agent.get("outputLanguage"), model_id=str(binding["modelId"]),
                skill_snapshots=tuple(item for item in raw_agent.get("skillSnapshot", []) if isinstance(item, dict)),
            ),
            goal=goal,
            assignment=AssignmentContext(
                assignment_id=scheduled.assignment_id,
                acceptance_criteria="; ".join(json.loads(assignment["acceptance_criteria_json"])),
                parent_message=str(proposal.get("objective", "Inspect the workspace.")),
            ),
            workspace_policy="Read-only session workspace. Never request or perform mutation.",
        )
        await self._db.execute(
            "UPDATE assignment_attempts SET context_selection_json = ? WHERE id = ? AND state = 'running'",
            (_safe_json(built.metadata.persistence_value()), scheduled.attempt_id),
        )
        await self._db.commit()
        deadline = time.monotonic() + wall_clock
        messages = (
            {"role": "system", "content": built.system_prompt},
            {"role": "user", "content": built.user_prompt},
        )
        request = ProviderRequest(
            request_id=f"specialist_{uuid.uuid4().hex}", model_id=str(binding["modelId"]), messages=messages,
            tools=tuple(_TOOL_SCHEMAS[name] for name in sorted(tools)) if max_calls else (),
            metadata={"sessionId": session_id, "assignmentId": scheduled.assignment_id},
        )
        call_count = 0
        input_tokens = output_tokens = 0
        normalized_cost: float | None = None
        text: list[str] = []
        evidence: list[dict[str, Any]] = []
        try:
            for iteration in range(max_iterations):
                prior_input, prior_output, prior_cost = input_tokens, output_tokens, normalized_cost
                await self._require_running(session_id, scheduled)
                if time.monotonic() >= deadline:
                    raise SchedulerRejected("specialist_wall_clock_limit", "The specialist reached its wall-clock limit before another model turn.")
                from app.services.budget_counter_service import BudgetCounterService, BudgetExceeded
                try:
                    await BudgetCounterService(self._db).record_model_iteration(session_id, scheduled.assignment_id)
                except BudgetExceeded as error:
                    raise SchedulerRejected("specialist_iteration_limit", "The specialist reached its model-iteration limit.") from error
                await AssignmentScheduler(self._db).checkpoint(
                    scheduled.attempt_id, {"iteration": iteration, "toolCalls": call_count}, count_iteration=False,
                )
                calls: list[ToolCall] = []
                turn_text: list[str] = []
                await self._provider_operation(session_id, scheduled.assignment_id, request, "running")
                provider_outcome = "failed"
                try:
                    try:
                        async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                            async for event in provider.stream(request):
                                await self._require_running(session_id, scheduled)
                                if isinstance(event, ToolCall):
                                    calls.append(event)
                                elif isinstance(event, TextDelta):
                                    turn_text.append(event.text)
                                elif isinstance(event, StructuredOutput) and isinstance(event.value, dict):
                                    summary = event.value.get("summary")
                                    if isinstance(summary, str):
                                        turn_text.append(summary)
                                    raw_evidence = event.value.get("evidence", [])
                                    if isinstance(raw_evidence, list):
                                        for item in raw_evidence:
                                            if not isinstance(item, dict):
                                                continue
                                            try:
                                                safe = Evidence.model_validate({
                                                    "kind": item.get("kind"),
                                                    "summary": _redact(str(item.get("summary", "")))[:800],
                                                    "artifactIds": [],
                                                })
                                            except Exception:
                                                continue
                                            evidence.append(safe.model_dump(by_alias=True, mode="json"))
                                elif isinstance(event, Usage):
                                    input_tokens = prior_input + (event.input_tokens or 0)
                                    output_tokens = prior_output + (event.output_tokens or 0)
                                    normalized_cost = (
                                        (prior_cost or 0) + event.cost_usd if event.cost_usd is not None else prior_cost
                                    )
                                    before_usage = await EventRepository(self._db).last_sequence(session_id)
                                    from app.services.budget_counter_service import BudgetCounterService, BudgetExceeded
                                    try:
                                        await BudgetCounterService(self._db).record_provider_usage(
                                            session_id, scheduled.assignment_id, input_tokens=input_tokens, output_tokens=output_tokens,
                                            normalized_cost=normalized_cost, duration_ms=0,
                                            cost_uncertainty="exact" if normalized_cost is not None and event.exact else ("estimated" if normalized_cost is not None else "unavailable"),
                                        )
                                    except BudgetExceeded as error:
                                        raise SchedulerRejected("specialist_usage_limit", "The specialist reached a configured usage limit.") from error
                                    usage_page = await EventRepository(self._db).page_after(session_id, after_sequence=before_usage)
                                    await self._publish(session_id, list(usage_page.events))
                                elif isinstance(event, (Cancelled, RetryableError, TerminalError)):
                                    raise SchedulerRejected("specialist_provider_failed", "The specialist provider could not complete the assignment.")
                    except TimeoutError as error:
                        await provider.cancel(request.request_id)
                        raise SchedulerRejected("specialist_wall_clock_limit", "The specialist reached its wall-clock limit.") from error
                    except SchedulerRejected as error:
                        if error.code == "specialist_superseded":
                            provider_outcome = "cancelled"
                        await provider.cancel(request.request_id)
                        raise
                    provider_outcome = "succeeded"
                finally:
                    await self._provider_operation(session_id, scheduled.assignment_id, request, provider_outcome, complete=True)
                text.extend(turn_text)
                if not calls:
                    summary = _redact("".join(text))[:800]
                    if not summary:
                        raise SchedulerRejected("specialist_result_missing", "The specialist returned no usable result.")
                    await AssignmentScheduler(self._db).complete_attempt(session_id, scheduled.attempt_id, output_summary=summary, evidence=evidence[:50])
                    return SpecialistResult(scheduled.assignment_id, summary, tuple(evidence[:50]))
                ids = [call.call_id for call in calls]
                if len(ids) != len(set(ids)) or any(not item for item in ids):
                    raise SchedulerRejected("specialist_tool_call_invalid", "The provider returned duplicate or missing tool call identifiers.")
                if call_count + len(calls) > max_calls:
                    raise SchedulerRejected("specialist_tool_limit", "The specialist reached its tool-call limit before another tool could start.")
                assistant: AssistantMessage = {"role": "assistant", "content": "".join(turn_text), "tool_calls": [
                    {"id": call.call_id, "name": call.name, "arguments": call.arguments} for call in calls
                ]}
                followups: list[ToolMessage] = []
                for call in calls:
                    result = await self._execute_tool(session_id, scheduled, call, tools, deadline=deadline)
                    followups.append({"role": "tool", "content": result, "tool_call_id": call.call_id, "name": call.name})
                    call_count += 1
                request = replace(request, request_id=f"{request.request_id}:tool:{iteration}", messages=(*request.messages, assistant, *followups))
            raise SchedulerRejected("specialist_iteration_limit", "The specialist reached its model-iteration limit.")
        except asyncio.CancelledError:
            await provider.cancel(request.request_id)
            raise
        except SchedulerRejected:
            raise
        except Exception as error:
            raise SchedulerRejected("specialist_runtime_failed", "The specialist stopped safely without exposing provider or workspace details.") from error

    async def _context(self, session_id: str, scheduled: ScheduledAssignment):
        async with self._db.execute(
            """SELECT assignment.*, proposal.proposal_json FROM assignments assignment
               JOIN assignment_proposals proposal ON proposal.assignment_id = assignment.id
               WHERE assignment.session_id = ? AND assignment.id = ?""",
            (session_id, scheduled.assignment_id),
        ) as cursor:
            assignment = await cursor.fetchone()
        if assignment is None:
            raise SchedulerRejected("assignment_missing", "The scheduled assignment was not found.")
        configuration = await SessionConfigurationService(self._db).current(session_id)
        raw = await SessionConfigurationService(self._db).raw_agent_snapshot(session_id, str(assignment["assignee_session_agent_id"]))
        async with self._db.execute("SELECT COALESCE(goal, task) AS goal FROM sessions WHERE id = ?", (session_id,)) as cursor:
            session = await cursor.fetchone()
        return assignment, json.loads(assignment["proposal_json"]), raw, str(session["goal"]), configuration.execution_limits

    async def _resolve(self, profile_id: str, model_id: str) -> Provider:
        if self._provider_resolver is not None:
            return await self._provider_resolver(profile_id, model_id)
        return await ProviderProfileService(self._db).runtime_provider(profile_id, model_id)

    async def _execute_tool(
        self, session_id: str, scheduled: ScheduledAssignment, call: ToolCall, allowed: set[str], *, deadline: float,
    ) -> str:
        if call.name not in allowed:
            raise SchedulerRejected("specialist_tool_denied", "The provider requested a tool outside the assignment allowlist.")
        from app.services.budget_counter_service import BudgetCounterService, BudgetExceeded
        try:
            await BudgetCounterService(self._db).record_tool_call(session_id, scheduled.assignment_id)
        except BudgetExceeded as error:
            raise SchedulerRejected("specialist_tool_limit", "The specialist reached its tool-call limit before another tool could start.") from error
        args = dict(call.arguments)
        tool_id = f"tool_{uuid.uuid4().hex}"
        summary = f"Run bounded read-only {call.name}."
        requested = await self._tool_event(session_id, scheduled, tool_id, call.name, "requested", summary)
        await self._publish(session_id, requested)
        started_at = _now_ms()
        started = await self._tool_event(session_id, scheduled, tool_id, call.name, "running", summary)
        await self._publish(session_id, started)
        try:
            workspace = await ProjectWorkspaceService(
                self._db, managed_root=Path(settings.db_path).expanduser().resolve().parent / "workspaces",
            ).workspace_for_session(session_id)
            tools = ScopedToolService(workspace)
            async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                if call.name == "read_file":
                    path = args.get("path")
                    if not isinstance(path, str):
                        raise WorkspaceError("read_file requires a path")
                    result = await asyncio.to_thread(tools.read_text, path, max_characters=100_000)
                elif call.name == "list_dir":
                    path = args.get("path", ".")
                    if not isinstance(path, str):
                        raise WorkspaceError("list_dir path must be a string")
                    result = "\n".join(await asyncio.to_thread(tools.list_directory, path))
                else:
                    query, path = args.get("query"), args.get("path", ".")
                    if not isinstance(query, str) or not isinstance(path, str):
                        raise WorkspaceError("search_files requires a query and optional path")
                    result = "\n".join(await asyncio.to_thread(tools.search_text, query, path))
            await self._require_running(session_id, scheduled)
            safe_result = result[:100_000]
            completed = await self._tool_event(session_id, scheduled, tool_id, call.name, "succeeded", "Read-only tool completed.", duration_ms=max(0, _now_ms() - started_at))
            await self._publish(session_id, completed)
            return safe_result
        except asyncio.CancelledError:
            completed = await self._tool_event(session_id, scheduled, tool_id, call.name, "cancelled", "Read-only tool was cancelled safely.", duration_ms=max(0, _now_ms() - started_at))
            await self._publish(session_id, completed)
            raise
        except SchedulerRejected as error:
            completed = await self._tool_event(session_id, scheduled, tool_id, call.name, "cancelled", "Read-only tool output was fenced after the session stopped or paused.", duration_ms=max(0, _now_ms() - started_at))
            await self._publish(session_id, completed)
            raise error
        except Exception as error:
            completed = await self._tool_event(session_id, scheduled, tool_id, call.name, "failed", "Read-only tool was denied or failed safely.", duration_ms=max(0, _now_ms() - started_at))
            await self._publish(session_id, completed)
            raise SchedulerRejected("specialist_tool_failed", "A read-only tool was denied or failed safely.") from error

    async def _tool_event(self, session_id: str, scheduled: ScheduledAssignment, tool_id: str, name: str, state: str, summary: str, duration_ms: int | None = None) -> list[StoredEvent]:
        async with transaction(self._db):
            events = EventRepository(self._db)
            if state == "requested":
                payload = {"toolExecutionId": tool_id, "assignmentId": scheduled.assignment_id, "toolName": name, "operationClass": "read_only", "requestSummary": summary}
                event = await events._append_in_transaction(event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="tool.requested", actor_id="system", payload=payload, payload_json=_safe_json(payload), timestamp_ms=_now_ms(), correlation_id=scheduled.assignment_id, command_id=None)
                await self._db.execute("""INSERT INTO tool_executions (id, session_id, assignment_id, tool_name, operation_class, request_summary, exit_state, requested_event_id, created_at_ms, updated_at_ms) VALUES (?, ?, ?, ?, 'read_only', ?, 'requested', ?, ?, ?)""", (tool_id, session_id, scheduled.assignment_id, name, summary, event.event_id, _now_ms(), _now_ms()))
            elif state == "running":
                payload = {"toolExecutionId": tool_id, "assignmentId": scheduled.assignment_id, "toolName": name}
                event = await events._append_in_transaction(event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="tool.started", actor_id="system", payload=payload, payload_json=_safe_json(payload), timestamp_ms=_now_ms(), correlation_id=scheduled.assignment_id, command_id=None)
                await self._db.execute("UPDATE tool_executions SET exit_state = 'running', updated_at_ms = ? WHERE id = ?", (_now_ms(), tool_id))
            else:
                payload = {"toolExecutionId": tool_id, "assignmentId": scheduled.assignment_id, "status": state, "resultSummary": summary, "durationMs": duration_ms or 0, "artifactIds": []}
                event = await events._append_in_transaction(event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="tool.completed", actor_id="system", payload=payload, payload_json=_safe_json(payload), timestamp_ms=_now_ms(), correlation_id=scheduled.assignment_id, command_id=None)
                await self._db.execute("UPDATE tool_executions SET exit_state = ?, result_summary = ?, duration_ms = ?, completed_event_id = ?, updated_at_ms = ? WHERE id = ?", (state, summary, duration_ms or 0, event.event_id, _now_ms(), tool_id))
        return [event]

    async def _provider_operation(self, session_id: str, assignment_id: str, request: ProviderRequest, state: str, *, complete: bool = False) -> None:
        operation_id = f"provider_{request.request_id}"
        async with transaction(self._db):
            if complete:
                await self._db.execute("UPDATE provider_operations SET state = ?, completed_at_ms = ? WHERE id = ? AND state = 'running'", (state, _now_ms(), operation_id))
            else:
                await self._db.execute("""INSERT INTO provider_operations (id, session_id, assignment_id, operation_kind, mutation_class, state, request_fingerprint, started_at_ms) VALUES (?, ?, ?, 'specialist', 'read_only', 'running', ?, ?)""", (operation_id, session_id, assignment_id, uuid.uuid5(uuid.NAMESPACE_URL, request.request_id).hex, _now_ms()))

    async def _require_running(self, session_id: str, scheduled: ScheduledAssignment) -> None:
        async with self._db.execute("""SELECT session.status, assignment.state, attempt.state AS attempt_state FROM sessions session JOIN assignments assignment ON assignment.session_id = session.id JOIN assignment_attempts attempt ON attempt.assignment_id = assignment.id WHERE session.id = ? AND assignment.id = ? AND attempt.id = ?""", (session_id, scheduled.assignment_id, scheduled.attempt_id)) as cursor:
            row = await cursor.fetchone()
        if row is None or row["status"] != "running" or row["state"] != "running" or row["attempt_state"] != "running":
            raise SchedulerRejected("specialist_superseded", "The session paused or stopped before specialist output could commit.")

    async def _publish(self, session_id: str, events: list[StoredEvent]) -> None:
        if not events:
            return
        from app.services.command_processor import event_wire_value
        values = [event_wire_value(event) for event in events]
        if self._publisher is not None:
            await self._publisher(session_id, values)
        else:
            from app.api.websocket import connection_hub
            await connection_hub.publish(session_id, values)
