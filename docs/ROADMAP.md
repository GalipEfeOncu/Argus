# Argus Delivery Roadmap

## Purpose and completion contract

This is the implementation sequence for the Coordinator-first Argus desktop
product. It is intentionally organized as independently testable vertical
slices. An implementation agent should be able to select the next unchecked
slice, follow its owned contracts and acceptance criteria, and leave the
repository in a releasable intermediate state.

The product is complete only when a user can select a local project, configure a
Coordinator and constrained team, run a provider-backed task in an isolated
workspace, observe the ordered collaboration timeline, use customized limits
and approval behavior, recover after restart, inspect evidence and diffs, and
install a signed desktop build on every supported platform.

Normative decisions live in:

- [PRODUCT.md](PRODUCT.md) for outcomes and non-goals;
- [ARCHITECTURE.md](ARCHITECTURE.md) for ownership and runtime boundaries;
- [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md) for algorithms, persistence,
  defaults, and evidence rules;
- [API.md](API.md) for REST, command, and event shapes;
- [UX_SPEC.md](UX_SPEC.md) for visible behavior and accessibility;
- [SECURITY.md](SECURITY.md) for permissions and non-bypassable denials.

When this roadmap conflicts with an authoritative contract, update the contract
and this roadmap together before coding.

## Delivery rules

For every slice:

1. Update the authoritative Pydantic/OpenAPI contract first when wire behavior
   changes.
2. Generate JSON Schema and TypeScript clients; never hand-maintain duplicate
   protocol types.
3. Add backend persistence/runtime behavior and migrations.
4. Update the shared frontend reducer, live transport, and simulator fixture.
5. Add success, malformed-input, permission, ordering, replay, and cancellation
   coverage proportional to the slice.
6. Update the authoritative documentation in the same change.
7. Run the narrowest verification scope, inspect the full diff, and record any
   check that could not run.
8. For performance-sensitive changes, run the applicable packaged-build fixture
   and attach before/after startup, RSS, CPU, bundle, and interaction results.

Do not begin a phase until the preceding phase exit gate passes. Within a phase,
slices are ordered by dependency unless explicitly marked parallel-safe. Do not
use LangGraph or another model graph as session topology; the persisted event
log, scheduler, assignments, gates, and counters own orchestration.

## Current baseline and migration target

The current repository contains a React shared-room prototype and simulator,
transitional FastAPI endpoints, SQLite scaffolding, individual role workers, and
a static in-memory `Planner → Builder → Reviewer ⇄ Builder → Tester` LangGraph.
Coordinator behavior, durable scheduling, generated REST clients, worktree
enforcement, configurable limits, approval grants, provider execution, replay,
and release hardening are not yet complete unless proven by current tests.

The migration must preserve a usable simulator while replacing the static graph
with this target:

```text
human → Coordinator → structured proposal → deterministic scheduler
                                             ├─ persisted assignment worker(s)
                                             ├─ policy/workspace services
                                             ├─ gates and budget service
                                             └─ ordered shared-room events
```

## Phase 0 — Contract and test foundation (✅ Completed; release certification deferred to Phase 7)

### 0.1 Freeze Coordinator-first contracts (✅ Completed)

Deliverables:

- Keep available team, required roles, configurable limits, approval behavior,
  Coordinator limit decisions, and shared-room behavior aligned across all
  documents linked above.
- Mark existing REST/WebSocket and static graph behavior as transitional.
- Define stable vocabulary: agent definition, session agent, available pool,
  required-role rule, assignment, attempt, gate evidence, grant, soft threshold,
  hard ceiling, decision, and workspace revision.
- Add a documentation link/check script that catches missing relative links,
  malformed Markdown, and stale generated-contract instructions.

Acceptance:

- No document describes a fixed role pipeline as target behavior.
- Coordinator is mandatory; excluded agents cannot be selected; required roles
  require eligible pool members.
- “No approval until completion” is specified as bounded preauthorization, not
  implicit or prompt-based permission.

Verification:

```bash
.agents/skills/argus-development/scripts/verify.sh docs
```

### 0.2 Establish automated test and generation infrastructure (✅ Completed)

Deliverables:

- Configure Vitest, Testing Library, pytest, pytest-asyncio, and temporary
  SQLite fixtures.
- Export the discriminated Pydantic event union to
  `contracts/session-events.schema.json` and generate
  `src/types/generated/session-events.ts`.
- Generate the REST client types from FastAPI OpenAPI.
- Add deterministic fake clock, ID generator, fake provider, and simulator
  scenario helpers.
- Add CI jobs for frontend type-check/test/build, backend import/test, contract
  drift, Rust format/clippy/test, docs, and secret scan.

Acceptance:

- Regeneration produces no uncommitted diff.
- One valid and one invalid fixture exist for every event/command union branch.
- CI fails on stale generated output or a hand-authored incompatible frontend
  event type.

### 0.3 Establish development-host performance tooling (✅ Completed; release certification deferred to Phase 7)

Deliverables:

- Add deterministic benchmark-contract tooling for first paint/interactivity,
  requested sidecar readiness, idle/active process-tree RSS, idle CPU, frontend
  chunks, packaged artifact composition, event replay, long tasks, and
  scroll/input responsiveness. The native package runner belongs to Phase 7.
- Add deterministic 100-event, 10,000-event, 5 MB diff, and 50 MB on-demand diff
  fixtures defined in [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md).
- Verify the deterministic benchmark tooling on the designated CachyOS x86_64
  development host. Label all resulting measurements as development calibration,
  never as release evidence.
- Defer native packaged baselines for Windows 10/11 x86_64, macOS Apple Silicon
  and Intel, and the Ubuntu 22.04-compatible Linux reference runner to Phase 7.
  Unavailable hardware is an explicit Phase 7 blocker; never invent, copy, or
  cross-compile measurements for another target.
- Emit machine-readable benchmark JSON and a human-readable comparison report.
  Retaining a rolling release baseline in CI artifacts belongs to Phase 7.
- Add size attribution for the web assets, Rust shell, Python runtime, each
  Python dependency/provider group, and installer resources.

Acceptance:

- Debug/Vite results cannot be submitted as release measurements.
- The benchmark fixture, schema validation, comparison, attribution, and
  regression-policy tests execute locally on the CachyOS development host.
- Later phases run their applicable deterministic performance tests on CachyOS;
  their results are development calibration only. Phase 7 enforces release
  budgets on every supported native target.

Current status (2026-07-18):

- ✅ The deterministic fixture generator, versioned result schema, release-only
  provenance validation, comparison report, hard-budget and 10% regression
  checks, and artifact-attribution tool are implemented and covered by CI.
- ✅ The fixture manifest includes the empty-launch, 100/10,000-event, 5 MB,
  50 MB on-demand, sidecar restart, and replay scenarios.
- ✅ The benchmark fixture, validation, comparison, attribution, and regression
  policy tests execute on the available CachyOS x86_64 development host.
- ℹ️ `npm run benchmark:release` intentionally emits an `unsupported` result
  until Phase 7 packages a native Tauri plus sidecar runner. It cannot create a
  release baseline during development.
- ℹ️ Windows x86_64, macOS Apple Silicon, macOS Intel, and Ubuntu 22.04-
  compatible Linux release runners are deferred Phase 7 blockers. No values may
  be estimated or copied from another platform.

Phase 0 exit (passed): contracts are internally consistent, test runners execute
locally, generated types have a single authoritative source, and deterministic
benchmark tooling is verified on the designated CachyOS development host. Native
release measurements and rolling cross-platform baselines are Phase 7 exit-gate
requirements.

## Phase 1 — Typed shared-room contract prototype

### 1.1 Event projection and transport boundary (✅ Completed)

Deliverables:

- Implement one pure session reducer for snapshot plus strictly ordered events.
- Buffer future sequences, ignore exact duplicates, reject conflicting duplicate
  event IDs, and request resync on a gap timeout or invalid payload.
- Define a transport interface shared by the simulator and live WebSocket.
- Model pending idempotent commands separately from confirmed server state.

Tests:

- Initial snapshot, ordered stream, duplicate event, gap recovery, reconnect from
  last sequence, stale snapshot, malformed payload, and command retry.

Current status (2026-07-19):

- ✅ The frontend has one pure canonical-event projection reducer with ordered
  buffering, exact-duplicate suppression, conflicting-ID/sequence detection,
  stale-snapshot protection, and resync requests.
- ✅ Both the deterministic simulator and the target WebSocket client use the
  same validated transport boundary. Pending commands retain their idempotency
  key until a correlated event confirms them.
- ✅ Reducer and transport tests cover the listed acceptance paths. The backend
  WebSocket runtime remains transitional until the Phase 2 durable control
  plane supplies the replay endpoint.

### 1.2 Coordinator-first timeline (✅ Completed)

Deliverables:

- Make unmentioned composer messages visibly target Coordinator.
- Render human, Coordinator, specialist, system, tool, assignment, handoff,
  evidence, gate, limit, decision, usage, diff, and error entries.
- Collapse specialist detail without removing events from the ordered room.
- Correlate streaming messages, tools, assignments, attempts, and artifacts.
- Window timeline rows with bounded overscan, preserve focus by stable event ID,
  and batch streaming paints to one animation-frame commit.
- Keep Shiki, large diff parsing, and nonessential animation code out of the
  first-load chunk; provide readable plain-text fallbacks.

Tests:

- Keyboard send, streaming interruption, explicit mention, collapsed detail,
  screen-reader announcement throttling, and correlation links.
- 10,000-event scroll/input benchmark, DOM-node ceiling, streaming render count,
  lazy-chunk assertion, reduced motion, and background-tab timer suspension.

Current status (2026-07-19):

- ✅ The shared room now renders directly from the canonical session projection.
  Every target event has a typed human, Coordinator, specialist, system, tool,
  assignment, handoff, evidence, gate, limit, decision, usage, diff, or error
  representation, with stable correlation links and artifact evidence retained.
- ✅ Unmentioned human messages visibly target Coordinator; explicit
  `@participant` mentions are sent as canonical command targets. Specialist
  detail can be collapsed without removing its ordered room event.
- ✅ The timeline uses measured-height virtualization with bounded overscan,
  stable event-ID focus/jumps, unread-event return-to-latest control,
  animation-frame streaming paint coalescing, throttled live announcements, and
  background-tab suspension. Diff enhancement loads only on request; plain text
  remains readable first.
- ✅ The typed simulator exercises real streaming deltas and correlated
  interruption, plus assignment/tool/diff/usage/handoff relationships. Frontend
  acceptance coverage includes keyboard send, mentions, collapsed detail,
  correlation, 10,000-event DOM bound, streaming batching, screen-reader
  throttling, and background return.

### 1.3 Session configuration UI (✅ Completed)

Deliverables:

- Implement the seven setup sections in [UX_SPEC.md](UX_SPEC.md).
- Coordinator cannot be disabled. Available agents are instances, not only role
  names. Required-role controls show eligibility and evidence requirements.
- Implement Quick, Balanced, Thorough, and Custom presets with fully visible
  resolved values.
- Validate zero/null limit semantics, cost/token units, incompatible gates,
  unsafe preauthorization, and missing models before start.
- Show a final plain-language authority and interruption summary.

Tests:

- Builder-only pool; automatic broad pool; Reviewer and Tester required; invalid
  required role; unlimited user ceiling; zero revisions; no-interruption mode;
  preset-to-Custom transition; full keyboard and focus order.

Current status (2026-07-20):

- ✅ The seven-section setup flow now creates a typed session configuration
  snapshot. Coordinator is mandatory; available agents are immutable instances,
  not role-name aliases, and the selected instance IDs remain visible to the
  simulator and legacy participant views.
- ✅ Quick, Balanced, Thorough, and Custom resolve all values in-place. The
  validator distinguishes blank ceilings from zero, checks model/evidence/gate
  compatibility, accepts decimal cost amounts, and prevents unsafe or
  impossible configurations before start.
- ✅ No-interruption mode shows exact selected capabilities and workspace scope,
  requires Autonomous acknowledgement that is invalidated by authority or scope
  changes, and keeps non-bypassable restrictions visible. Direct-write mode
  warns that rollback is limited and requires acknowledgement.
- ✅ The typed simulator validates configuration even when called outside the
  UI, respects the selected pool and pre-authorized writes, and preserves agent
  instance identity. Frontend coverage now includes 38 tests for configuration,
  simulator, transport, and timeline behavior. Durable backend persistence and
  runtime enforcement remain Phase 2 responsibilities.

### 1.4 Runtime controls and terminal states (✅ Completed)

Deliverables:

- Context panel groups Available, Active, Waiting, and Done participants.
- Display required gates, remaining limits, active grants, current writer, and
  configuration version.
- Implement pending pause/resume/cancel/interrupt/update/approval/decision UI.
- Render all required lifecycle states and distinguish complete, partial,
  cancelled, recoverable failure, and terminal failure.
- Keep Pause and Cancel permanently reachable.

Simulator scenarios:

- Dynamic Builder-only success.
- Builder → Reviewer revision → Reviewer approval → Tester evidence.
- Repeated finding reaches limit and Coordinator delivers partial.
- Preauthorized task completes without an approval prompt.
- Denied capability causes Coordinator replan.
- Reconnect during streaming and during `waiting_decision`.

Current status (2026-07-20):

- ✅ The runtime context projects participant groups, required gates, all eight
  remaining user ceilings, active grants, current writer, configuration version,
  command-pending state, and distinct completed, partial, cancelled, recoverable,
  and terminal failure states from canonical events.
- ✅ Pause and Cancel remain in the shared-room header when the context panel is
  hidden. Approval, decision, interruption, pause/resume/cancel, and configuration
  commands stay pending until a correlated event resolves them.
- ✅ Future team, required-gate, approval-behavior, and limit-resolution patches
  are visible before sending. The typed simulator models a non-mutating
  consequence preview followed by an explicit `confirmConsequences: true`
  acceptance; the durable backend preview/confirm response loop remains a
  Phase 2 control-plane responsibility.
- ✅ The deterministic simulator covers Builder success, review/test evidence,
  partial completion, prompt-free preauthorization, denied-capability replanning,
  streaming and decision reconnects, plus recoverable and terminal failures.
  Accepted configuration patches update the client snapshot for subsequent edits.

Phase 1 exit: every target event and command has accessible visible behavior
using typed simulation, with no dependency on a live provider.

## Phase 2 — Durable control plane and isolated workspace

### 2.1 SQLite schema and migrations (✅ Completed)

Deliverables:

- Add versioned migrations for every table in
  [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md), foreign keys, uniqueness,
  indexes, UTC epoch-millisecond timestamps, and migration metadata.
- Implement repositories with explicit transactions; no API layer issues raw
  orchestration SQL.
- Store immutable events and configuration versions; project read models from
  events and prove rebuild equivalence.
- Never store provider credentials, raw private reasoning, or unredacted secret
  material.

Tests:

- Fresh database, upgrade from current schema, interrupted migration rollback,
  uniqueness, event sequence concurrency, projection rebuild, and secret scan.

Current status (2026-07-23):

- ✅ SQLite now upgrades through recorded, checksummed, transactional migrations.
  The pre-migration prototype schema remains readable while the durable control
  plane adds every Phase 2 persistence table, foreign-key relationships,
  uniqueness constraints, and bounded-read indexes.
- ✅ Backend HTTP/WebSocket handlers use repositories for session persistence;
  orchestration SQL and transaction boundaries live below the API layer.
- ✅ Event writes allocate a unique per-session sequence in one transaction;
  immutable event projection rebuild and rejection of recognizable credentials
  or private-reasoning fields are covered by backend tests.
- ✅ The Phase 2.1 acceptance tests cover fresh initialization, prototype
  upgrade, simulated interrupted migration rollback, concurrent sequencing,
  projection rebuild equivalence, and persistence secret scanning.

### 2.2 Event store and command processor

Deliverables:

- Allocate monotonic per-session sequences transactionally.
- Persist accepted command outcome before broadcast.
- Implement command idempotency and return the original correlated result.
- Add snapshot creation, replay after sequence, bounded retention-safe paging,
  and projection checksums.
- Add indexed cursor pagination for timeline and artifact summaries; prohibit
  unbounded event-log hydration in interactive endpoints.
- Implement lifecycle transition table including `waiting_approval`,
  `waiting_decision`, and `completed_partial`.

Tests:

- Concurrent append, duplicate commands across reconnect, illegal transitions,
  crash before/after commit, snapshot plus replay equivalence, and slow client.
- Query-plan snapshots, bounded row counts, 10,000-event replay throughput, and
  memory stability across repeated page navigation.

Current status (2026-07-23):

- ✅ The canonical session transport commits command outcomes atomically before
  broadcasting them, validates the lifecycle transition table, and returns the
  original correlated result for reconnect retries.
- ✅ Checksummed event snapshots, bounded sequence replay, timeline cursor
  pages, and artifact-summary cursor pages are persisted and covered by query
  plan and 10,000-event bounded-page tests.

### 2.3 Project and workspace service (✅ Completed)

Deliverables:

- Register and canonicalize projects; detect git, dirty state, nested repos,
  symlinks, case sensitivity, and unsupported paths.
- Create managed worktree/branch by default and copy-on-write snapshot for
  non-git projects; support acknowledged direct-write mode.
- Scope read, search, write, shell, test, and git tools to the resolved workspace.
- Implement project writer lock and per-session writer lease with timeout,
  renewal, recovery, and auditable release.
- Produce diff artifacts and workspace revision checksums after mutations.

Security tests:

- `..` escape, symlink escape/race, shell injection, environment secret
  redaction, destructive command denial, lock contention, stale lease recovery,
  original-directory protection, and cleanup after crash.

Current status (2026-07-24):

- ✅ Local projects are canonicalized and registered with git, dirty-tree,
  nested-repository, symbolic-link, and case-sensitivity inspection. Sessions
  provision a managed git worktree by default or a non-git snapshot; direct
  writes require an explicit acknowledged request.
- ✅ Session-bound tools use descriptor-relative path checks, no-follow snapshot
  copying, argv-only execution, constrained read commands, and an OS sandbox
  requirement for project-controlled test/build commands. Mutations acquire a
  writer lease, create a checksummed diff artifact, and leave an audit record.
- ✅ Durable project locks and writer leases support renewal, stale recovery,
  release/reacquisition, startup orphan cleanup, and focused security coverage
  for escapes, symlink races, command denial, secret forwarding, isolation, and
  crash recovery.

### 2.4 Session configuration service

Deliverables:

- Implement `POST /sessions`, normalized defaults, validation error codes,
  acknowledgement flow, immutable agent snapshots, and policy hashes.
- Implement optimistic `session.configuration.update` with consequence preview.
- Apply reductions immediately to future dispatch and interrupt invalid active
  work after explicit consequence confirmation.
- Never decrease consumed counters or silently invalidate historical evidence.

Tests:

- Pool/gate validation, duplicate IDs, stale version, add/remove agent, reduce
  limit below consumed value, permission increase/decrease, restart persistence,
  and idempotent update.

Phase 2 exit: sessions, events, configuration, commands, workspaces, locks, and
diffs survive process restart and pass workspace escape and idempotency tests.

## Phase 3 — Dynamic Coordinator and assignment runtime

### 3.1 Provider-neutral worker protocol

Deliverables:

- Define normalized streaming, structured output, tool call, usage, finish,
  cancellation, retryable error, and terminal error interfaces.
- Implement a scripted fake provider capable of malformed actions, disconnects,
  tool requests, slow streams, and deterministic usage.
- Build bounded context from agent snapshot, goal, assignment, unresolved human
  instructions, relevant events, summary, and artifact references.
- Log context selection metadata without content that exposes secrets or private
  reasoning.
- Split provider adapters into lazy production dependency groups and verify that
  configuring one provider does not import every provider SDK.
- Keep one Python sidecar with task workers; do not spawn one runtime per agent.

Performance acceptance:

- Requested cold sidecar readiness, ready-idle RSS, and idle CPU meet the budgets.
- Import tracing proves unused provider and LangGraph modules are absent from a
  minimal execution path.
- If an individual worker does not use LangGraph, production packaging omits it.

### 3.2 Structured Coordinator cycle

Deliverables:

- Define and validate Coordinator actions: assignments, wait, ask user, final,
  partial, and stop.
- Resolve unmentioned user messages to Coordinator and explicit mentions to a
  scheduler-visible participant instruction.
- Permit one bounded correction for malformed/unauthorized Coordinator output.
- Require concise visible routing and final summaries with evidence references.
- Prevent Coordinator from granting permissions, changing session config,
  selecting excluded agents, or claiming gate satisfaction.

Tests:

- Builder-only pool, irrelevant role skipped, excluded role attempted, missing
  capability, malformed action correction, repeated invalid action, user
  supersede while streaming, and final claim with unmet gate.

### 3.3 Assignment scheduler

Deliverables:

- Persist proposals, validation outcomes, assignments, attempts, handoffs, and
  terminal results.
- Dispatch bounded parallel read-only work and serialize mutations with the
  writer lease.
- Support cancellation propagation, participant interrupt, retry policy,
  checkpoints, and recovery of orphaned attempts.
- Specialists may propose follow-ups, but only validated Coordinator/scheduler
  actions create executable work.
- Remove static graph session orchestration after equivalent fake-provider
  coverage passes; retain LangGraph only inside an individual worker if useful.

Tests:

- Assignment tree, parent cancellation, parallel read ordering, mutating
  serialization, lease loss, worker crash/recovery, direct handoff policy,
  duplicate proposal, and static graph removal regression.

### 3.4 First real vertical task

Deliverables:

- Connect the live WebSocket transport to the same reducer used by simulation.
- Run Coordinator → Builder against an isolated fake project, request/consume a
  scoped write grant, generate a diff, and complete with evidence.
- Support live pause, resume, cancel, human correction, and reconnect.

End-to-end acceptance:

- No simulator data remains after live snapshot load.
- Every visible operation has a persisted event and correlation.
- Cancel prevents additional provider/tool output from mutating state.
- The resulting diff is reviewable and the original project is unchanged.

Phase 3 exit: the static fixed pipeline is no longer session orchestration and a
Coordinator dynamically completes one provider-neutral isolated coding task.

## Phase 4 — Gates, customizable limits, and approval autonomy

### 4.1 Required-role gate engine

Deliverables:

- Implement applicability evaluation for `always`, `when_changes`, and
  `when_capability_used`.
- Add built-in structured evidence schemas and deterministic validators for
  Planner, Builder/UI Agent, Reviewer, and Tester.
- Tie review/test evidence to workspace revision and invalidate it after mutation.
- Route unsatisfied applicable gates to eligible available agents before success.
- Support explicit user acceptance of partial completion without relabeling it
  full success.

Tests:

- Required Reviewer/Tester, conditional gate not applicable, missing eligible
  agent, invalid model prose, stale evidence, multiple minimum completions,
  custom evidence schema, and partial outcome.

### 4.2 Budget and counter service

Deliverables:

- Implement session-, assignment-, finding-, and tool-scoped counters for every
  configurable limit.
- Reserve counters transactionally with dispatch, return unused reservations on
  pre-start failure only, and never grant a free retry after started work.
- Emit one soft warning per crossing and hard-limit events before excess work.
- Display normalized token/cost uncertainty when a provider lacks exact usage.
- Keep internal resource guards distinct from user-configured limits.

Tests:

- Zero, one, finite, and null ceilings; ratio warning; concurrent reservations;
  restart; provider usage correction; cost unavailable; wall-clock pause rules;
  and boundary off-by-one cases.

### 4.3 Loop detection and Coordinator initiative

Deliverables:

- Normalize review finding and failure fingerprints and compute workspace/diff
  no-progress checksums without secrets.
- Count revisions by accepted mutating follow-up for the same finding.
- Implement `ask_user`, `coordinator_decides`, and `stop` limit resolution.
- Restrict the Coordinator decision invocation to one tool-free structured
  choice: reassign, change approach, deliver partial, or stop.
- Validate that reassign/change-approach cannot evade the reached hard ceiling,
  excluded pool, required gates, or remaining assignment budget.

Tests:

- Same finding phrased differently, distinct finding at same path, unchanged
  diff, repeated test signature, reassign evasion, decision timeout, malformed
  decision, no remaining assignee, partial delivery, and human interrupt.

### 4.4 Approval and grant engine

Deliverables:

- Implement Strict, Balanced, Autonomous, and acknowledged Expert unrestricted
  profiles plus capability overrides.
- Implement `ask_each_time`, `ask_by_policy`, `preauthorize_session`, and
  `deny_interactive` behavior.
- Persist once/scope/session grants with expiry and policy hash; evaluate policy
  in the precedence order defined by [SECURITY.md](SECURITY.md).
- Show exact start-time authority summary and obtain required acknowledgements.
- Ensure no-interruption mode automatically denies ungranted requests and lets
  Coordinator adapt without manufacturing approval.

Security tests:

- Approval bypass, stale grant, broader path/capability than grant, policy hash
  change, revoked grant during tool request, preauthorization restart,
  non-bypassable operation in every profile, and Coordinator fake approval.

Phase 4 exit: user-selected teams, required roles, limits, loop handling, and all
approval behaviors work end to end and remain enforced after reconnect/restart.

## Phase 5 — Roles, skills, models, and provider breadth

### 5.1 Agent definitions and capability routing

Deliverables:

- Version built-in Coordinator, Planner, Builder, Reviewer, Tester, and UI Agent
  templates.
- Support overrides and custom roles with declared capabilities, model binding,
  skill IDs, tool allowlist, permission profile, evidence contract, and language.
- Snapshot definitions into sessions so later edits do not alter active work.
- Route by capabilities and evidence requirements, using role names only for
  built-in UX defaults.

### 5.2 Local skill packages

Deliverables:

- Import and validate manifests, paths, content hashes, references, requested
  tools, and permissions.
- Display trust/capability review and keep imports disabled until enabled.
- Prevent traversal, symlink escape, mutable post-validation content, prompt
  injection from gaining tools, and session-policy escalation.
- Snapshot enabled skill content/version into assignment context metadata.

### 5.3 Native providers and credentials

Deliverables:

- Implement OpenAI, Anthropic, Google, and OpenAI-compatible adapters against
  the normalized worker protocol.
- Discover supported models/capabilities and allow an explicit manual model ID.
- Store keys in the OS credential service through Tauri; persist references only.
- Normalize streaming, tools, structured output fallback, cancellation, retries,
  rate limits, usage, and redacted errors.
- Add provider contract suites using recorded synthetic fixtures without keys.

Acceptance:

- Every provider completes the same fake-project conformance scenario or is
  visibly marked unsupported for required capabilities.
- Switching a role model does not change scheduler, permission, event, or gate
  semantics.

Phase 5 exit: users can customize roles and local skills and execute equivalent
Coordinator flows across supported providers without credential leakage.

## Phase 6 — Recovery, observability, and project completion workflow

### 6.1 Crash and reconnect recovery

Deliverables:

- Recover sessions, projections, grants, counters, decisions, leases, worker
  checkpoints, and orphaned tool executions after backend or app restart.
- Reconcile provider operations whose remote outcome is unknown; never replay a
  mutating tool call solely because its response was lost.
- Add bounded event compaction/snapshots without deleting the append-only audit
  source under the current retention policy.
- Add graceful sidecar idle shutdown only when there is no running session,
  pending command, approval/decision, tool process, lease, or recovery work;
  restart transparently without losing drafts or cached shell navigation.

### 6.2 Diff review and acceptance

Deliverables:

- Provide file/tree diff, artifact evidence, test/review results, unmet gates,
  limit history, usage, and Coordinator summary.
- Let the user accept/apply changes through a policy-checked operation, reject
  them, export a patch, or start a follow-up assignment/session.
- Detect original project drift before apply and offer a safe conflict workflow.
- Clean up or retain worktrees according to an explicit user choice and status.

### 6.3 Local observability

Deliverables:

- Add structured redacted logs, runtime health, queue/lease status, provider
  latency, event lag, and usage diagnostics.
- Provide a user-exportable support bundle with configuration shapes and event
  summaries but no credentials, raw prompts by default, private reasoning, or
  project file contents without explicit selection.
- Add degraded-mode UI for provider outage, disk full, database lock, corrupted
  event, sidecar crash, and credential-store unavailability.

Phase 6 exit: an interrupted task recovers without duplicate mutation, and the
user can safely evaluate and apply or export the final isolated result.

## Phase 7 — Desktop integration and release hardening

### 7.1 Tauri and sidecar lifecycle

Deliverables:

- Package the FastAPI runtime as a version-matched sidecar with authenticated
  localhost communication, dynamic port selection, readiness, graceful stop,
  crash restart policy, and single-instance coordination.
- Minimize Tauri capabilities for dialogs, credential access, process lifecycle,
  and approved filesystem roots.
- Reject connections from unexpected origins and prevent another local process
  from controlling a session.
- Render the shell before sidecar readiness, package a target-triple-specific
  frozen sidecar, and strip development packages and unused provider groups.
- Replace fixed ports with authenticated dynamic allocation and ensure the
  process tree terminates on normal exit, forced close, update, and uninstall.
- Reduce Rust/Tokio feature flags and Tauri plugins to those proven necessary;
  produce a binary-size attribution report after each change.

### 7.2 Cross-platform quality

Deliverables:

- Support declared Windows, macOS, and Linux versions; document git/shell
  prerequisites and non-git fallback.
- Build natively on Windows 10 22H2/11 x86_64, macOS 12+ arm64/x86_64, and an
  Ubuntu 22.04-compatible Linux x86_64 baseline; test current Ubuntu and Debian
  stable. Add Linux ARM64 only with a native runner and separate release gate.
- Ship signed NSIS or MSI on Windows, signed/notarized app bundle and DMG on
  macOS, and AppImage plus at least one native Linux package family.
- Test path encoding, spaces, long paths, case behavior, line endings, executable
  bits, symlinks, process cancellation, keychain variants, and sleep/resume.
- Complete keyboard-only, screen-reader smoke, contrast, zoom, reduced-motion,
  large-timeline virtualization, and low-resource testing.
- Test WebView2 availability/bootstrap on Windows, the declared WebKit/system
  version range on macOS, and WebKitGTK/glibc compatibility on Linux.
- Run every performance fixture on each release artifact; record cold/warm
  startup, process-tree RSS/CPU, installer size, long-task count, and 10,000-event
  interaction results.

### 7.3 Supply chain and release

Deliverables:

- Pin dependencies, generate SBOM, audit licenses/vulnerabilities, scan secrets,
  and verify reproducible clean builds where feasible.
- Sign/notarize installers, publish checksums and versioned release notes, and
  test install/upgrade/uninstall with preservation of user configuration.
- Add database/config backup before migrations and documented rollback/recovery.
- Publish threat model, privacy statement, vulnerability contact, known limits,
  and operator troubleshooting.

Release candidate gates:

- All verification scopes pass on every supported platform.
- Every hard performance and footprint budget passes on release-equivalent
  reference hardware; deviations have no waiver path for the first stable release.
- Provider conformance, fake-provider end-to-end, recovery, workspace escape,
  approval bypass, loop limit, required gate, and update tests pass.
- A clean machine can install, configure a provider, run a Coordinator task with
  a restricted pool and no-interruption policy, recover after forced restart,
  review the audit trail, and safely apply the diff.
- No credential or private reasoning appears in SQLite, logs, events, exports,
  fixtures, crash reports, or UI.

Phase 7 exit: signed release artifacts satisfy the complete product contract.

## Final definition of done

Argus is finished for this product scope when all phase gates pass and the
following scenarios are automated:

1. Coordinator chooses only Builder from a broader allowed pool for a simple
   change and completes without unnecessary agents.
2. A Builder-only restricted pool is enforced even when Coordinator requests a
   Reviewer.
3. Required Reviewer and Tester gates block success until fresh evidence exists.
4. Three equivalent review findings reach the configured ceiling; Coordinator
   uses an allowed decision without exceeding it.
5. A fully preauthorized workspace task finishes with no approval prompt, while
   an outside-workspace request remains denied and visible.
6. User pause, participant interrupt, policy reduction, and cancel take effect
   during streaming and tool execution.
7. Restart/reconnect preserves event order, counters, grants, assignments,
   decisions, and workspace state without duplicate mutation.
8. Custom roles and local skills cannot exceed session capabilities.
9. Every supported provider satisfies normalized execution semantics.
10. The user reviews evidence and applies or exports an isolated diff from a
    signed desktop build.
11. Cold/warm launch, sidecar startup, idle CPU/RSS, first-load assets, installer
    size, and 10,000-event interaction pass the release budgets on Windows,
    macOS, and Linux artifacts.

The legacy static session graph, transitional protocol types, simulator-only
claims, and undocumented approval paths must be removed before declaring the
product complete.
