# Argus Architecture

## Purpose

Argus is a local-first desktop workspace for transparent multi-agent software development. It combines a Tauri desktop client, a React interface, and a local FastAPI runtime that coordinates model providers and project tools.

The product is not modeled as a fixed agent chain. A session is a shared, ordered collaboration room with a deterministic control plane and model-driven participants.

## Orchestration contract

The user talks to the Coordinator by default. The Coordinator plans delegation
and emits structured assignment proposals; it does not directly start workers,
grant permissions, extend hard limits, or declare an unverified success. The
scheduler validates each proposal against the current versioned session configuration
and current policy before persisting and dispatching it.

```text
Human message
    ↓
Coordinator worker ── assignment proposal ──→ Scheduler
                                                ├─ validate agent pool/role
                                                ├─ validate budgets/policy/lease
                                                ├─ persist ordered event
                                                └─ dispatch specialist worker
                                                            ↓
Shared timeline ← result/handoff/tool/diff events ←─────────┘
    ↓
Coordinator evaluates evidence, required roles, and terminal state
```

A session configuration distinguishes:

- `availableAgentIds`: the only specialists the Coordinator may assign;
- `requiredRoleRules`: quality gates that must be satisfied before success;
- `executionLimits`: user-selected soft thresholds and runtime-enforced hard
  ceilings;
- `approvalPolicy`: which capabilities are pre-authorized, ask-on-demand, or
  denied, plus how limit decisions are handled;
- `workspacePolicy`: worktree, managed snapshot, or explicitly acknowledged
  direct-write behavior.

The Coordinator itself is not part of `availableAgentIds`; it is a mandatory
session participant. A required role must also have at least one eligible agent
in the available pool. Session creation rejects invalid combinations.

## System overview

```text
Tauri Desktop App
├── React client
│   ├── Project/session navigation
│   ├── Shared timeline and composer
│   ├── Agent roster, assignments, usage, diffs, approvals
│   └── Typed REST/WebSocket clients
├── Tauri bridge
│   ├── Native dialogs and credential-store access
│   └── Local backend lifecycle
└── FastAPI local runtime
    ├── Deterministic control plane
    ├── Event store and session projections
    ├── Coordinator and agent execution workers
    ├── Provider adapters and skill registry
    ├── Workspace, worktree, tool, and approval services
    └── SQLite persistence
```

## Lightweight runtime strategy

Tauri 2 remains the desktop shell because it uses the platform webview instead
of shipping a second browser runtime. React 19, Vite, typed reducers, and Zustand
remain the UI stack. FastAPI/Python remains the orchestration sidecar for the
initial product because the provider and agent ecosystem reduces implementation
risk, but it is isolated behind REST/WebSocket contracts and must earn its place
against the performance budgets.

The following rules keep that stack lightweight:

- render the app shell immediately and start the sidecar asynchronously only
  when durable/project/session data is first needed;
- keep one backend process and bounded worker tasks, never one Python process per
  agent;
- import provider SDKs and optional agent-loop integrations only when their
  configured provider or worker starts;
- keep LangGraph out of session topology and omit it from production packaging
  if no individual worker requires it;
- split syntax highlighting, diff viewers, settings routes, and other heavy UI
  features into lazy chunks; perform highlighting and large parsing off the UI
  thread when it would exceed one frame;
- virtualize timelines, agent activity, file trees, and large diffs; query events
  and artifacts in bounded pages;
- subscribe to events instead of polling and stop timers/animation when the app
  is hidden, reduced-motion is enabled, or the relevant element is off-screen;
- allow an idle sidecar with no live session, pending command, or recovery work
  to shut down after a bounded grace period and restart transparently;
- compile only required Tauri/Tokio/plugin features and package one native
  sidecar per target triple.

The Python boundary is intentionally replaceable. A Rust rewrite is considered
only if representative packaged builds cannot meet the budgets after dependency
splitting, lazy imports, frozen-sidecar optimization, and profiling. Such a
rewrite must preserve the protocol and persistence contracts rather than fork
product behavior.

## Cross-platform contract

Release builds are produced natively in a CI matrix, not assumed portable from
one host:

- Windows 10/11 x86_64 using WebView2 and signed NSIS or MSI packaging;
- macOS on Apple Silicon and Intel for the declared support window, signed and
  notarized as an app bundle/DMG;
- Linux x86_64 with an oldest-supported glibc/WebKitGTK build baseline, shipping
  at least AppImage plus one native package family; Linux ARM64 is added only
  after a native runner passes the same gates.

Platform adapters own path rules, process trees, signals, credential stores,
shell selection, executable suffixes, line endings, webview differences, and
installer lifecycle. Product/runtime code consumes normalized interfaces and
must not branch on platform outside those adapters.

## Control plane and collaboration plane

The control plane owns facts that must be deterministic: event sequencing,
agent-pool eligibility, required-gate state, policy checks, approvals, project
locks, writer leases, cancellation, retries, budgets, loop detection,
persistence, and recovery.

The collaboration plane contains the visible Coordinator and agents. They receive a bounded projection of the shared timeline, can create messages, request tools, assign work, hand off tasks, and produce artifacts. Model output never bypasses the control plane.

LangGraph may be used for an individual agent's tool loop and checkpointing. It is not the source of truth for session topology; the current static `Planner → Builder → Reviewer → Tester` graph will be replaced by the event-driven session runtime.

### Assignment topology

Assignments form a persisted tree, not an in-memory graph. Each assignment has
one assignee, a parent cause, acceptance criteria, operation class, budget,
attempt number, and terminal result. Only the Coordinator can create root
specialist assignments. A specialist can propose a handoff or follow-up, but
the scheduler routes it through the Coordinator unless the session policy
explicitly permits direct handoffs.

Read-only assignments may execute in bounded parallelism. Mutating assignments
are serialized by the writer lease. Required-role checks evaluate terminal
assignment evidence rather than whether an agent merely started.

### Limit and loop resolution

The budget service tracks revision count, assignment attempts, model
iterations, tool calls, elapsed time, tokens, normalized cost, and concurrency.
It also detects repeated normalized review findings, identical failure
signatures, and no-progress diff hashes.

A soft threshold creates `limit.warning` and gives the Coordinator a chance to
adapt. A hard ceiling prevents another counted action and creates
`limit.reached`. According to the configured resolution mode, the scheduler
either asks the user, invokes a bounded Coordinator decision, or stops. A
Coordinator decision may reassign within remaining budgets, deliver a partial
result, or stop; it may not reset counters or expand authority.

## Session lifecycle

```text
created → preparing → running ⇄ paused
                          ├→ waiting_approval ⇄ running
                          ├→ waiting_decision ⇄ running
                          ├→ completed
                          ├→ completed_partial
                          ├→ cancelled
                          └→ failed
```

Each session has an append-only event log. The client receives a snapshot then events in increasing `sequence` order. On reconnect it requests events after its last confirmed sequence. Commands carry idempotency keys.

Different projects may run sessions concurrently. Only one mutating session can hold a project writer lock in the MVP. Within a session, read-only work may overlap while only one participant holds the writer lease.

## Participants, roles, and skills

Participants are `human`, `system`, `coordinator`, or `agent`. Built-in agent definitions provide a prompt, capabilities, default skills, tool permissions, and suggested model capabilities. A user can override those values or create a custom capability-based role. Coordinator routing uses declared capabilities and current assignment evidence; role names alone are not authorization.

A skill package contains a manifest, instructions, optional reference material, required tools, and requested permissions. Imported skills are validated and require explicit enabling before use.

## Provider layer

Provider adapters normalize streaming, tool calls, usage, model metadata, and provider errors for:

- OpenAI
- Anthropic
- Google
- OpenAI-compatible endpoints, including OpenRouter and local model servers

Provider keys are stored through the native credential service. The runtime only sees a short-lived resolved credential and never emits it in events, logs, exports, or SQLite records.

## Workspace and tools

The default workspace is a session-specific git worktree and branch. Filesystem, search, shell, and git tools run through a policy-aware service scoped to that workspace. A tool execution records its request, approval state, result summary, duration, and related artifacts in the timeline.

Non-git projects use a managed snapshot workspace. Direct modification of the original directory is an explicit policy choice.

## Data ownership

SQLite persists project metadata, sessions, immutable events, participant and
policy snapshots, available-agent membership, required-role rules, limit
counters, approvals, assignments, artifacts, diffs, usage, and workspace
metadata. The selected project remains the source of code; Argus stores
orchestration metadata and isolated worktree state.

## Vocabulary

Stable terms used across all Argus contracts. When prose elsewhere conflicts with
these definitions, update the prose to match.

| Term | Definition |
| --- | --- |
| **agent definition** | A versioned record that describes one participant: role name, system prompt, model binding, enabled skills, tool allowlist, permission profile, evidence contract, and output language. Definitions are snapshotted into a session at creation and are immutable for the life of that session. |
| **session agent** | An immutable snapshot of an agent definition bound to a specific session. Session agents are the active participants; editing an agent definition after session creation has no effect on running sessions. |
| **available pool** | The set of session agents the Coordinator is permitted to assign work to in a given session, expressed as `availableAgentIds` in the session configuration. The Coordinator may use any member when useful and may never select an excluded agent. |
| **required-role rule** | A completion gate that specifies a role, an applicability condition (`always`, `when_changes`, or `when_capability_used`), a success-evidence kind, and a minimum completion count. The session cannot reach `completed` while any applicable required-role rule is unsatisfied. |
| **assignment** | A persisted unit of work delegated to one session agent. It carries a parent cause, acceptance criteria, operation class (`read_only` or `mutating`), budget, attempt number, and a terminal result. Only the Coordinator creates root specialist assignments; the scheduler validates and persists every assignment proposal before dispatching it. |
| **attempt** | One worker invocation for an assignment. An assignment may produce multiple attempts when retries are permitted and budget remains. Each attempt records its configuration version, checkpoint, usage, normalized outcome, and failure fingerprint. |
| **gate evidence** | Structured proof produced by a completed assignment that satisfies a required-role rule. Evidence is tied to the workspace revision at which it was produced; a subsequent mutation invalidates Reviewer and Tester evidence. Evidence is validated by deterministic code, not by model prose. |
| **grant** | A persisted, bounded authorization for a capability and workspace scope, created either at session start (`preauthorize_session`) or in response to an approval request. Grants carry an expiry, a scope, and the policy hash under which they were issued. A grant cannot widen its original scope or override non-bypassable denials. |
| **soft threshold** | A configurable limit value at which the budget service emits a `limit.warning` event and gives the Coordinator an opportunity to adapt. Crossing the soft threshold does not stop work. |
| **hard ceiling** | A configurable limit value at which the budget service prevents the next counted action, emits a `limit.reached` event, and triggers the configured limit-resolution mode (`ask_user`, `coordinator_decides`, or `stop`). A Coordinator decision at a hard ceiling may not reset counters or expand authority. |
| **decision** | A structured choice recorded after a limit is reached or the session enters `waiting_decision`. For `coordinator_decides`, the Coordinator selects one of: `reassign`, `change_approach`, `deliver_partial`, or `stop`. For `ask_user`, the human makes the choice. The scheduler validates and persists the decision before acting on it. |
| **workspace revision** | An immutable checkpoint of the session workspace, identified by a content checksum. A workspace revision is created after each accepted mutating operation. Required-role gate evidence is tied to the revision at which it was produced and is invalidated when a later mutation changes the checksum. |

See [API.md](API.md) for protocol contracts, [SECURITY.md](SECURITY.md) for enforcement, and [UX_SPEC.md](UX_SPEC.md) for the visible product behavior.
