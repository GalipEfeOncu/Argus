# Argus Implementation Specification

This document closes the planning phase. It defines the MVP implementation decisions that must not be reinvented while building individual slices.

## 1. Runtime ownership

Argus uses a deterministic Python session runtime with model-driven participants.

- The **Coordinator** is a visible, configurable agent. It creates assignments, explains handoffs, and may request parallel read-only work.
- The **scheduler** is not an LLM. It validates commands, owns ordering, grants writer leases, enforces policies, starts/stops workers, records events, and applies budgets.
- An agent receives work only from a persisted assignment or an explicit human mention.
- A session has one active writer lease. Read-only assignments may run concurrently when they do not request a writer lease.
- LangGraph is allowed inside one agent's tool loop and checkpoint implementation. It must not encode the overall team topology or bypass the scheduler.

### Scheduler rules

1. Append every accepted command and runtime outcome to the session event log before broadcasting it.
2. Process events in increasing per-session sequence order.
3. Reject duplicate client commands by `commandId` and return the previous outcome.
4. Allow a human command to pause, cancel, interrupt, or supersede an agent assignment immediately.
5. Stop an assignment when its token, iteration, wall-clock, or tool budget is exceeded; emit an actionable stop reason.
6. Never start a mutating assignment without a writer lease and a policy grant.

## 2. Context construction

Do not pass an unbounded raw transcript to every model invocation.

For each assignment, build context in this order:

1. Immutable agent definition snapshot: role name, system prompt, enabled skills, tool allowlist, output language, and model binding.
2. Session goal, project identity, workspace policy, and current assignment acceptance criteria.
3. The assignment's parent message, explicit handoff, and unresolved human instructions.
4. Relevant recent timeline messages and tool/artifact summaries.
5. A compact durable session summary generated or updated by the Coordinator after meaningful milestones.
6. Referenced project files only when requested through scoped tools.

All context selection decisions are recorded in assignment metadata. Provider private reasoning is never persisted or displayed.

## 3. Persistence model

SQLite is the source of truth for local orchestration metadata. Store timestamps as UTC epoch milliseconds and IDs as UUID strings.

| Table | Required responsibility |
| --- | --- |
| `projects` | Canonical project path, git metadata, display name, and project lock state |
| `sessions` | Goal, lifecycle status, policy snapshot, worktree metadata, counters, summary, and timestamps |
| `events` | Append-only event envelope, payload JSON, sequence, actor, correlation ID, and command ID when applicable |
| `agent_definitions` | Built-in template versions, user overrides, and custom role definitions |
| `session_agents` | Immutable agent-definition/model/skill snapshot used by a session |
| `skills` | Imported manifest, content hash, trust state, source path, and enablement state |
| `assignments` | Parent, assignee, state, acceptance criteria, budgets, and lease references |
| `approvals` | Requested capability/scope, decision, grant duration, resolver, and audit timestamps |
| `tool_executions` | Tool request, normalized result summary, exit state, duration, and artifact references |
| `artifacts` | Diffs, exports, file references, and checksums |
| `provider_profiles` | Non-secret provider metadata and OS credential reference only |

Events are never updated or deleted during normal operation. Read models may be rebuilt from them. Session deletion is a deliberate future retention policy, not an implicit cascade.

## 4. Agent definitions and skill packages

Built-in roles are versioned templates: Coordinator, Planner, Builder, Reviewer, Tester, and UI Agent. A custom role uses the same schema and cannot gain capabilities that its selected session policy disallows.

### Agent definition fields

```json
{
  "id": "uuid",
  "name": "Security reviewer",
  "kind": "builtin_override | custom",
  "baseRole": "reviewer | null",
  "systemPrompt": "...",
  "modelBinding": { "providerProfileId": "uuid", "modelId": "..." },
  "skillIds": ["uuid"],
  "toolAllowlist": ["read_file", "search_files"],
  "permissionProfile": "balanced",
  "outputLanguage": "en"
}
```

### Local skill manifest

Each imported local skill directory contains `skill.json` and instruction files. MVP manifest:

```json
{
  "schemaVersion": 1,
  "id": "com.example.accessibility-review",
  "name": "Accessibility review",
  "version": "1.0.0",
  "description": "Checks UI changes for accessibility regressions.",
  "instructions": "SKILL.md",
  "references": ["references/wcag.md"],
  "requestedTools": ["read_file", "search_files"],
  "requestedPermissions": ["workspace.read"]
}
```

Import validates the schema, resolves every path inside the package directory, hashes content, displays requested capabilities, and leaves the skill disabled until the user enables it. Marketplace/distribution support is not part of the MVP.

## 5. Workspace and permission matrix

Every tool request has a capability, workspace scope, operation class, and approval state.

| Capability | Strict | Balanced default | Autonomous | Expert unrestricted |
| --- | --- | --- | --- | --- |
| Read/list/search inside workspace | approval | allow | allow | allow |
| Safe tests without network | approval | allow | allow | allow |
| Write/edit in session worktree | approval | request scoped grant | allow | allow |
| Dependency install or network shell | approval | approval | allow | allow |
| Git branch/commit operations | approval | approval | approval | allow |
| Original project directory write | approval | approval with warning | approval with warning | allow |
| Outside-workspace, destructive, or secret-exfiltration command | deny | deny | deny | explicit expert confirmation per command |

The default workspace is a git worktree at a managed Argus location. For a non-git project, create a copy-on-write snapshot. A direct-write session must visibly state that rollback is limited.

## 6. Protocol and generated types

The backend Pydantic discriminated union is the canonical event source. Wire JSON is camelCase.

1. Export `GET /contracts/session-events` schema to `contracts/session-events.schema.json`.
2. Generate `src/types/generated/session-events.ts` with `json-schema-to-typescript`.
3. Commit generated output.
4. Add a CI check that fails if regenerating changes tracked output.
5. Derive REST client types from FastAPI OpenAPI using `openapi-typescript` with the same check.

The legacy WebSocket message names are transitional. The runtime migration emits only the event types documented in [API.md](API.md), then removes the legacy reducer after the frontend consumes the new envelope.

## 7. UI acceptance criteria

The UI simulator and live transport use the same reducer. Before connecting a live provider, verify each event visually and in component tests:

- timeline ordering, streaming, tool result, assignment, handoff, diff, usage, approval, recoverable error, and terminal error;
- empty, loading, connected, reconnecting, paused, approval, cancelled, completed, and failed session states;
- pending command feedback and idempotent retry state;
- keyboard use, focus handling, reduced motion, and live-region announcements;
- no mock data is shown after a real session projection has loaded.

## 8. Test and CI policy

Add the following before Phase 2 is declared complete:

- **Frontend:** Vitest and Testing Library for reducers, stores, simulator, and stateful UI components.
- **Backend:** pytest, pytest-asyncio, FastAPI integration tests, and temporary SQLite databases.
- **Contract:** schema-generation drift, valid/invalid event fixtures, event ordering, replay, and command idempotency.
- **Security:** workspace escape, symlink, shell injection, approval bypass, secret redaction, and direct-write warnings.
- **End-to-end:** one fake-provider scenario from project selection through accepted diff.
- **CI:** frontend type-check/test/build, backend test/import, Rust format/clippy/test, contract-generation drift, and secret scan.

## 9. Build order and phase gates

Build only one vertical slice at a time. Do not start a later phase while its predecessor exit criteria are incomplete.

1. **Phase 1:** complete the simulator, reducer, typed transport abstraction, UI states, accessibility, and contract generation.
2. **Phase 2:** project registration, worktree service, SQLite event store, fake provider, Coordinator/Planner/Builder loop, human intervention, and diff approval.
3. **Phase 3:** Reviewer/Tester/UI templates, custom roles, local skill importer, capability routing, and budgets.
4. **Phase 4:** native providers, credential store, replay/recovery, bounded parallel sessions, and observability.
5. **Phase 5:** packaged sidecar, least-privilege Tauri permissions, cross-platform CI, release artifacts, and security hardening.

A phase is complete only when its behavior is implemented, automated tests pass, documentation reflects the result, and the next phase no longer depends on an undecided design choice.
