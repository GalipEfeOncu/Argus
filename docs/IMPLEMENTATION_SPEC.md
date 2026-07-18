# Argus Implementation Specification

This document closes the planning phase. It defines the MVP implementation decisions that must not be reinvented while building individual slices.

## 1. Runtime ownership

Argus uses a deterministic Python session runtime with model-driven participants.

- The **Coordinator** is a visible, configurable agent. It creates assignments, explains handoffs, and may request parallel read-only work.
- The **scheduler** is not an LLM. It validates commands, owns ordering, grants writer leases, enforces policies, starts/stops workers, records events, and applies budgets.
- An agent receives work only from a persisted assignment or an explicit human mention.
- A session has one active writer lease. Read-only assignments may run concurrently when they do not request a writer lease.
- LangGraph is allowed inside one agent's tool loop and checkpoint implementation. It must not encode the overall team topology or bypass the scheduler.
- The Coordinator is mandatory and receives every unmentioned human message.
  Specialists are dynamically selected only from the session's available pool.
- Required roles are evidence gates, not fixed graph nodes. Success is forbidden
  while an applicable required gate is unsatisfied.

### Scheduler rules

1. Append every accepted command and runtime outcome to the session event log before broadcasting it.
2. Process events in increasing per-session sequence order.
3. Reject duplicate client commands by `commandId` and return the previous outcome.
4. Allow a human command to pause, cancel, interrupt, or supersede an agent assignment immediately.
5. Stop an assignment when its token, iteration, wall-clock, or tool budget is exceeded; emit an actionable stop reason.
6. Never start a mutating assignment without a writer lease and a policy grant.
7. Validate every assignment proposal against the current configuration version,
   available pool, declared capabilities, remaining budgets, and permission policy.
8. Invoke required-role assignments before allowing `completed`; emit
   `completed_partial` only after a user or configured Coordinator decision.
9. Enforce hard limits before dispatch. Coordinator may decide the outcome at a
   limit but may not change counters, grants, team membership, or hard ceilings.
10. Record normalized loop signals for repeated findings, repeated failures, and
    unchanged diffs; never persist private reasoning in those fingerprints.

### Coordinator cycle

For each accepted human goal or specialist result, the runtime performs:

1. Build the bounded Coordinator context and current session projection.
2. Ask for one structured action: create assignments, wait, request a user
   decision, deliver final, deliver partial, or stop.
3. Validate the action deterministically and persist its outcome.
4. Dispatch accepted read-only work up to the configured parallel limit or one
   mutating assignment with the writer lease.
5. Feed terminal results and gate state back to the Coordinator.
6. Permit final success only when acceptance criteria and all applicable gates
   have validated evidence.

Malformed or unauthorized Coordinator output produces a recoverable error and
one bounded correction attempt. A second invalid response stops the cycle and
uses the configured decision policy.

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
| `session_configurations` | Versioned available pool, required-role rules, execution limits, approval behavior, acknowledgements, and policy hash |
| `skills` | Imported manifest, content hash, trust state, source path, and enablement state |
| `assignments` | Parent, assignee, state, acceptance criteria, budgets, and lease references |
| `assignment_attempts` | Worker invocation, configuration version, checkpoint, usage, normalized outcome, and failure fingerprint |
| `gate_evidence` | Required rule, producing assignment, evidence kind, validation state, and artifact references |
| `limit_counters` | Scope, counter kind, consumed value, threshold, warning state, and last correlated event |
| `approvals` | Requested capability/scope, decision, grant duration, resolver, and audit timestamps |
| `tool_executions` | Tool request, normalized result summary, exit state, duration, and artifact references |
| `artifacts` | Diffs, exports, file references, and checksums |
| `provider_profiles` | Non-secret provider metadata and OS credential reference only |

Events are never updated or deleted during normal operation. Read models may be rebuilt from them. Session deletion is a deliberate future retention policy, not an implicit cascade.

Configuration rows are immutable versions. Assignment and gate projections may
be updated transactionally for query performance, but every transition must be
reconstructable from events. Counter increments and the action they authorize
occur in one transaction so crashes cannot grant a free retry.

## 4. Session configuration

The API shape and validation rules are authoritative in [API.md](API.md).
Backend defaults must be explicit constants, returned in normalized responses,
and covered by snapshot tests. The initial product defaults are:

| Setting | Default |
| --- | --- |
| Available team | Planner, Builder, Reviewer, Tester, and UI Agent instances that are configured |
| Required roles | Reviewer on file changes when an eligible Reviewer is configured; Tester when an eligible Tester and test command are available |
| Revision per normalized finding | 3 |
| Assignment attempts | 8 |
| Model iterations per assignment | 20 |
| Tool calls per assignment | 100 |
| Session wall clock | 4 hours |
| Parallel read-only assignments | 3 |
| Permission profile | Balanced |
| Approval behavior | `ask_by_policy` |
| Limit resolution | `coordinator_decides` |

Users may set supported ceilings to `null` after a warning that provider,
process, platform, cancellation, and non-bypassable safety guards still apply.
The backend retains internal emergency guards against resource exhaustion; they
are deployment safety limits, are reported honestly when reached, and are not
presented as user task policy.

Required-role evidence validators are code, not prompts. Built-in validators:

- Planner: a versioned plan artifact satisfying configured acceptance fields;
- Builder/UI Agent: a non-empty diff or an explicit verified no-change result;
- Reviewer: an approved structured review tied to the current diff checksum;
- Tester: a completed test execution tied to the current workspace revision;
- custom role: a registered JSON-schema evidence contract.

Any subsequent mutation invalidates Reviewer and Tester evidence tied to an old
workspace revision.

## 5. Agent definitions and skill packages

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

## 6. Workspace and permission matrix

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

Approval behavior follows [SECURITY.md](SECURITY.md). `preauthorize_session`
creates persisted, bounded grants at start; `deny_interactive` converts an
otherwise interactive approval into a denial event. Neither mode changes the
permission matrix or grants capabilities omitted from the session snapshot.

## 7. Limits and loop detection

Counters use explicit scopes: session, assignment, finding fingerprint, or tool
execution. All comparisons happen before the next counted action. Revision count
increments when a workspace-mutating follow-up is accepted for the same
normalized finding, not when review prose is emitted.

Normalize review findings from structured fields: category, rule identifier,
affected repository-relative path, symbol or line anchor, and redacted semantic
summary. Normalize failures from tool, exit class, test identifier, and redacted
error class. Compute no-progress from workspace tree/diff checksums. Hashes must
not contain credentials or raw prompts.

Soft warnings occur once per threshold crossing. At a hard limit:

- `ask_user`: transition to `waiting_decision`;
- `coordinator_decides`: run exactly one tool-free decision invocation with a
  small separate decision budget;
- `stop`: fail the assignment and allow normal Coordinator finalization if its
  own cycle budget remains.

Reassignment cannot evade a finding-scoped limit. Changing approach is allowed
only when it creates a materially different acceptance strategy and consumes an
available assignment attempt. `deliver_partial` creates `completed_partial` and
lists unmet criteria and gates. Only the user can later promote or resume it.

## 8. Protocol and generated types

The backend Pydantic discriminated union is the canonical event source. Wire JSON is camelCase.

1. Export `GET /contracts/session-events` and `GET /contracts/session-commands` schemas to `contracts/` from their Pydantic adapters.
2. Generate `src/types/generated/session-events.ts` and `src/types/generated/session-commands.ts` with `json-schema-to-typescript`.
3. Export FastAPI OpenAPI to `contracts/openapi.json` and derive `src/types/generated/rest.ts` with `openapi-typescript`.
4. Run `npm run generate:contracts` to regenerate all of those files; commit the outputs and never edit them manually.
5. Add a CI check that fails if regenerating changes tracked output.

The legacy WebSocket message names are transitional. The runtime migration emits only the event types documented in [API.md](API.md), then removes the legacy reducer after the frontend consumes the new envelope.

## 9. UI acceptance criteria

The UI simulator and live transport use the same reducer. Before connecting a live provider, verify each event visually and in component tests:

- timeline ordering, streaming, tool result, assignment, handoff, diff, usage, approval, recoverable error, and terminal error;
- empty, loading, connected, reconnecting, paused, approval, cancelled, completed, and failed session states;
- pending command feedback and idempotent retry state;
- keyboard use, focus handling, reduced motion, and live-region announcements;
- no mock data is shown after a real session projection has loaded.
- available pool, required gates, resolved limits, grants, counter consumption,
  and configuration version are visible and update only from server events;
- coordinator-first, direct mention, no-interruption, limit decision, evidence
  invalidation, and partial completion flows are keyboard accessible.

## 10. Test and CI policy

Current local test runners are `npm run test` for the frontend and
`(cd backend && .venv/bin/python3 -m pytest -q)` for the backend. The
repository verification entry points run these checks together with their
respective type-check/build or import checks:

```bash
.agents/skills/argus-development/scripts/verify.sh frontend
.agents/skills/argus-development/scripts/verify.sh backend
```

Add the following before the corresponding roadmap phase is declared complete:

- **Frontend:** Vitest and Testing Library for reducers, stores, simulator, and stateful UI components.
- **Backend:** pytest, pytest-asyncio, FastAPI integration tests, and temporary SQLite databases.
- **Contract:** schema-generation drift, valid/invalid event fixtures, event ordering, replay, and command idempotency.
- **Orchestration:** pool exclusion, required-gate enforcement, dynamic routing,
  mutating serialization, parallel reads, malformed Coordinator action, every
  limit resolution, and revision-evasion prevention.
- **Security:** workspace escape, symlink, shell injection, approval bypass, secret redaction, and direct-write warnings.
- **Recovery:** crash between counter reservation and dispatch, active policy
  reduction, stale configuration version, reconnect during a decision, and
  evidence invalidation after mutation.
- **End-to-end:** one fake-provider scenario from project selection through accepted diff.
- **CI:** frontend type-check/test/build, backend test/import, Rust format/clippy/test, contract-generation drift, and secret scan.

## 11. Build order and phase gates

Build only one vertical slice at a time. Do not start a later phase while its predecessor exit criteria are incomplete.

The authoritative execution order and per-slice acceptance criteria are in
[ROADMAP.md](ROADMAP.md). Implementation must follow its dependency order; this
specification owns the runtime decisions that each slice implements.

## 12. Performance and footprint budgets

Performance measurements use signed or release-equivalent packaged builds with
telemetry disabled. CI records results by OS, architecture, application version,
sidecar version, dataset, and hardware class. Until dedicated reference machines
exist, use a four-core CPU, 8 GB RAM, SSD, and a supported OS installation as the
minimum reference class. Never compare development-server or debug builds to
these budgets.

### Release budgets

| Metric | Target | Hard gate |
| --- | --- | --- |
| First window interactive, cold start | p50 ≤ 1.5 s | p95 ≤ 3.0 s |
| First window interactive, warm start | p50 ≤ 0.8 s | p95 ≤ 1.5 s |
| Sidecar ready after requested, cold | p50 ≤ 2.5 s | p95 ≤ 5.0 s |
| Idle CPU after 30 s, no active session | ≤ 0.5% typical | ≤ 1% p95 |
| Idle total RSS, shell plus ready sidecar | ≤ 180 MB typical | ≤ 250 MB p95 |
| Shell-only RSS before sidecar | ≤ 100 MB typical | ≤ 150 MB p95 |
| Active first-load JavaScript, gzip | ≤ 350 KB | ≤ 500 KB |
| Active first-load CSS, gzip | ≤ 80 KB | ≤ 120 KB |
| Compressed installer excluding AppImage | ≤ 120 MB typical | ≤ 180 MB |
| Linux AppImage | ≤ 180 MB typical | ≤ 250 MB |
| Timeline interaction at 10,000 events | 60 fps target | no task > 100 ms during normal scroll/input |
| Composer-to-pending feedback | ≤ 50 ms target | ≤ 100 ms p95 |
| Pause/cancel pending feedback | ≤ 50 ms target | ≤ 100 ms p95 |

Provider model latency, user tools, dependency installation, and test duration
are reported separately and do not count as UI latency. Their streaming and
cancellation handling must still keep the UI responsive.

Budgets are initial engineering targets, not measured claims about the current
prototype. Phase 0 records the baseline on every supported OS. A budget may be
changed only with a documented benchmark, user-visible impact analysis, and the
same review as an architecture decision; it must not be relaxed merely to make
CI pass.

### Measurement fixtures

Maintain reproducible fixtures for empty launch, 100-event session, 10,000-event
session, 5 MB diff, 50 MB diff opened on demand, three parallel read-only agents,
one mutating agent, sidecar idle shutdown/restart, and reconnect replay. Record:

- time to native window, first paint, interactive shell, sidecar ready, session
  ready, and first streamed token;
- shell, webview child, sidecar, and worker RSS separately;
- main-thread long tasks, rendered DOM node count, dropped frames, event replay
  throughput, database query count, CPU wakeups, and packaged artifact contents;
- compressed/uncompressed size by frontend chunk, Rust binary, Python runtime,
  Python package, provider adapter, and platform resource.

### Implementation constraints

- Route-level and feature-level code splitting is required. Shiki, diff parsing,
  charting, and animation libraries must not enter the initial chunk unless the
  initial screen visibly uses them.
- The timeline and diff viewer must use windowing with stable item measurement;
  the DOM node count must remain bounded as event count grows.
- Zustand selectors must be narrow and stable. Streaming deltas may update only
  the affected message/assignment projection, not recreate the full timeline.
- Batch high-frequency stream events to at most one visual commit per animation
  frame while persisting every ordered event.
- SQLite queries used by interactive views require indexes, limits, and query
  plans in tests. Do not load a complete session event log or diff into memory.
- Python provider packages use lazy imports. Production dependency groups must
  allow unused providers and development/test packages to be absent from a
  target sidecar.
- Avoid `uvicorn[standard]`, broad Tokio feature sets, and always-on Tauri
  plugins unless benchmarks or required functionality justify them.
- No periodic status polling while WebSocket/native events are healthy. Timers
  must have ownership, cleanup, visibility behavior, and a test.

## 13. Supported desktop targets

The first stable release supports Windows 10 version 22H2 and Windows 11 on
x86_64; macOS 12 or newer on Apple Silicon and Intel; and Linux x86_64 built on
an Ubuntu 22.04-compatible glibc/WebKitGTK 4.1 baseline and tested on current
Ubuntu and Debian stable. Other distributions may run the AppImage but are not
claimed supported until added to the matrix. Linux ARM64 is a planned target
that becomes supported only after native build and performance runners pass all
gates. Each release matrix must build and test on the target OS because
installer, webview, keychain, process, and filesystem behavior cannot be
certified by cross-compilation alone.

Every supported target must pass install, first launch, sidecar start/stop,
provider credential storage, project selection, worktree/snapshot, shell and test
process cancellation, reconnect/restart, update, uninstall, and the performance
budgets above. Platform-specific exclusions must be visible before release and
cannot silently degrade safety or orchestration semantics.

A phase is complete only when its behavior is implemented, automated tests pass, documentation reflects the result, and the next phase no longer depends on an undecided design choice.
