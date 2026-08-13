# Argus Delivery Roadmap

## Purpose and completion contract

This is the implementation sequence for the Coordinator-first Argus desktop
product. It is intentionally organized as independently testable vertical
slices. An implementation agent should be able to select the next unchecked
slice, follow its owned contracts and acceptance criteria, and leave the
repository in a releasable intermediate state.

The roadmap implementation is complete only when a user can select a local
project, configure a Coordinator and constrained team, run a provider-backed
task in an isolated workspace, observe the ordered collaboration timeline, use customized limits
and approval behavior, recover after restart, inspect evidence and diffs, and
produce native desktop artifacts for every supported platform. Publishing those
artifacts additionally requires [pre-publish verification](PUBLISH_CHECKLIST.md).

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

## Cross-phase delivery controls

These controls run throughout delivery without authorizing product work from a
later phase or allowing a probe to satisfy that phase's exit gate.

### Release-readiness runway

- At every phase exit, run the narrowest available packaged-shell, sidecar,
  provider-contract, upgrade, and platform smoke probes. Record unavailable
  probes without inferring a pass; one platform's result never certifies another
  platform.
- Keep the native CI matrix, installer skeleton, sidecar composition report, and
  provider conformance harness executable as soon as their dependencies exist.
  A feasibility probe may discover risk early, but it may not ship target
  behavior or mark a later roadmap slice complete.
- Attach development-host results only as calibration. Clean-client, credential,
  signing/notarization, assistive-technology, and reference-hardware checks live
  in [PUBLISH_CHECKLIST.md](PUBLISH_CHECKLIST.md). They block publication for an
  affected target, not roadmap phase completion.

### Evidence-linked completion records

- Every newly completed slice records its completion date, source change,
  verification commands and results, relevant generated or benchmark artifacts,
  and every skipped check with its blocker. Use `this change` as the source while
  the work is uncommitted; the commit or pull request containing the status then
  becomes the durable reference. Never invent a future commit hash.
- A checked heading or prose status without this evidence is not sufficient to
  pass a slice or phase gate. Phase exits also confirm contract generation,
  documentation agreement, a clean focused diff, and no unresolved release-risk
  regression introduced by the phase.
- CI artifacts may expire, so durable summaries retain the tool version, target,
  result, and source commit needed to reproduce the evidence without copying
  credentials, private reasoning, or project data into the repository.

Use this block directly below a new or updated completion status:

```text
Completion evidence (YYYY-MM-DD):
- Source: this change | <commit/PR/tag>
- Verification: <commands and summarized results>
- Artifacts/benchmarks: <durable references or not applicable>
- Deferred/unavailable: none | <check and explicit reason>
```

### Product-maturity milestones

- **Alpha — Phase 5 exit:** an installable internal/developer preview exercises
  customizable roles, local skills, and supported provider adapters. It is not
  production-ready and may still lack complete recovery and apply workflows.
- **Beta — Phase 6 exit:** the product is feature-complete for the 1.0 scope and
  may enter a bounded user pilot after recovery, diff acceptance, and degraded
  modes pass. New scope requires an explicit roadmap change.
- **Release candidate — Phase 7:** the codebase and native build automation may
  enter a stabilization window. Publishing an RC additionally requires the
  pre-publish checklist. Only release blockers, security fixes, compatibility
  fixes, and evidence corrections may change the candidate.
- Stable `1.0.0` is permitted only after Phase 7 exit, the final definition of
  done, and the pre-publish checklist pass. Version selection and synchronized
  metadata follow
  [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md#14-versioning-and-release-train).

## Current baseline and migration target

The initial baseline contained a React shared-room prototype and simulator,
transitional FastAPI endpoints, SQLite scaffolding, individual role workers, and
a static in-memory `Planner → Builder → Reviewer ⇄ Builder → Tester` LangGraph.
Phase 3.3 removes that graph in favour of durable scheduling; remaining phases
continue the generated-client, provider-execution, replay, and release-hardening
work under the current tests.

The migration preserves a usable simulator while replacing the static graph
with this target:

```text
human → Coordinator → structured proposal → deterministic scheduler
                                             ├─ persisted assignment worker(s)
                                             ├─ policy/workspace services
                                             ├─ gates and budget service
                                             └─ ordered shared-room events
```

## Phase 0 — Contract and test foundation (✅ Completed; native certification is pre-publish)

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

### 0.3 Establish development-host performance tooling (✅ Completed; native certification is pre-publish)

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
  and Intel, and the Ubuntu 22.04-compatible Linux reference runner to the
  pre-publish checklist. Never invent, copy, or cross-compile measurements for
  another target.
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
  compatible Linux reference measurements are pre-publish gates. No values may
  be estimated or copied from another platform.

Phase 0 exit (passed): contracts are internally consistent, test runners execute
locally, generated types have a single authoritative source, and deterministic
benchmark tooling is verified on the designated CachyOS development host. Native
release measurements and rolling cross-platform baselines are pre-publish
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

### 2.2 Event store and command processor (✅ Completed)

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

### 2.4 Session configuration service (✅ Completed)

Deliverables:

- ✅ Implemented `POST /sessions`, normalized defaults, validation error codes,
  acknowledgement flow, immutable agent snapshots, and policy hashes.
- ✅ Implemented optimistic `session.configuration.update` with consequence preview.
- ✅ Reductions apply immediately to future dispatch and interrupt invalid active
  work after explicit consequence confirmation.
- ✅ Consumed counters are never decreased and historical evidence is retained.

Tests:

- ✅ Pool/gate validation, duplicate IDs, stale version, add/remove agent, reduce
  limit below consumed value, permission increase/decrease, restart persistence,
  and idempotent update.

Phase 2 exit: sessions, events, configuration, commands, workspaces, locks, and
diffs survive process restart and pass workspace escape and idempotency tests.

## Phase 3 — Dynamic Coordinator and assignment runtime

### 3.1 Provider-neutral worker protocol (✅ Completed)

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

Current status (2026-07-24):

- ✅ The backend exposes a provider-neutral stream contract for text, structured
  output, tool calls, usage, completion, cancellation, retryable failures, and
  terminal failures.
- ✅ A deterministic, credential-free scripted provider covers malformed output,
  disconnects, tool requests, slow streams, cancellation, and exact usage.
- ✅ Assignment context is ordered and bounded; selection metadata is logged and
  stored with each assignment attempt using IDs and a fingerprint rather than
  prompt content.
- ✅ Production provider and optional agent-loop dependencies are split into
  lazy extras. A minimal sidecar import verifies that unused provider and
  LangGraph modules are absent; worker execution uses bounded in-process tasks.

### 3.2 Structured Coordinator cycle (✅ Completed)

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

Current status (2026-07-24):

- ✅ Coordinator responses use a strict action union for assignment proposals,
  wait, ask-user, final, partial, and stop outcomes. The deterministic cycle
  allows exactly one correction and enforces the configured resolution after a
  second invalid response.
- ✅ Human messages now create durable scheduler-visible participant
  instructions: unmentioned messages target Coordinator and explicit mentions
  target one immutable session participant. Streaming Coordinator work can be
  superseded by newer human input.
- ✅ Coordinator routing validates the available pool and declared
  capabilities, while final delivery rejects unmet required gates. Its action
  contract has no authority to grant permissions, change configuration, or
  satisfy gates.

### 3.3 Assignment scheduler (✅ Completed)

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

Current status (2026-07-26):

- ✅ The durable scheduler records every Coordinator proposal, validation
  decision, assignment tree edge, attempt checkpoint/outcome, handoff, and
  terminal result in SQLite. Duplicate proposal IDs return their original
  assignment rather than creating work twice.
- ✅ Read-only assignments start up to the configured parallel limit. Mutating
  assignments obtain the session/project writer lease and remain serialized;
  cancellation, participant interruption, bounded retry, checkpointing, and
  orphaned-attempt recovery all leave durable, safe state for a restart.
- ✅ Specialist follow-ups are recorded as Coordinator-routed handoffs. The
  singular static agent-graph WebSocket endpoint and its fixed LangGraph role
  pipeline have been removed; canonical shared-room transport remains at
  `/ws/sessions/{session_id}`.

### 3.4 First real vertical task (✅ Completed)

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

Current status (2026-07-26):

- ✅ New sessions are created by the local runtime and load through the canonical
  replayable WebSocket reducer rather than launching simulator data. A created
  live session starts once its canonical snapshot arrives; reconnect replays
  the same persisted room events.
- ✅ The provider-neutral reference task now runs from live session commands:
  Coordinator routes an isolated Builder assignment, the user grants the
  bounded `workspace.write` capability, and the Builder records tool activity,
  a reviewable diff artifact, evidence, and terminal status without modifying
  the selected project.
- ✅ Pause, resume, cancel, human correction, and reconnect are covered on the
  live transport. Cancellation and participant interruption serialize with an
  in-flight workspace mutation, so accepted cancellation fences later output.

Phase 3 exit: the static fixed pipeline is no longer session orchestration and a
Coordinator dynamically completes one provider-neutral isolated coding task.

## Phase 4 — Gates, customizable limits, and approval autonomy (✅ Completed)

### 4.1 Required-role gate engine (✅ Completed)

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

Current status (2026-07-26):

- ✅ The deterministic gate engine evaluates `always`, `when_changes`, and
  accepted `when_capability_used` assignments; it routes pending Reviewer and
  Tester work before a session can claim full success.
- ✅ Built-in Planner, Builder/UI Agent, Reviewer, and Tester evidence is
  structured and validated by code. Custom roles use a session-snapshotted,
  explicitly supported JSON-Schema subset; unsupported contracts are rejected
  during configuration.
- ✅ Reviewer and Tester evidence is tied to the workspace checksum and is
  invalidated after a later mutation. The reference live vertical task now
  queues applicable review gates rather than bypassing them.
- ✅ Partial Coordinator outcomes preserve unmet requirements and wait for an
  explicit human acceptance before ending as `completed_partial`, never as
  full completion.

### 4.2 Budget and counter service (✅ Completed)

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

Current status (2026-07-26):

- ✅ Persistent, scoped counters cover assignment attempts, model iterations,
  tool calls, revisions, session tokens/cost, runnable wall-clock time, and
  parallel read-only capacity. Dispatch reserves its attempt and capacity in
  the same database transaction; started attempts remain spent across restart.
- ✅ Soft warnings are deduplicated per counter scope, while hard-limit events
  are recorded before the requested excess work can begin. Writer leases remain
  independent internal resource guards.
- ✅ Provider usage supports exact, estimated, and unavailable normalized cost;
  late provider corrections adjust totals by their durable delta. Paused time
  does not consume the wall-clock budget.

### 4.3 Loop detection and Coordinator initiative (✅ Completed)

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

Current status (2026-07-26):

- ✅ Review findings, failure outcomes, and unchanged workspace/diff states are
  reduced to durable redacted SHA-256 fingerprints with occurrence counts. No
  raw review prose, prompt, secret, or tool-output body is retained for loop
  detection.
- ✅ Only an accepted mutating Coordinator follow-up bound to an already known
  finding fingerprint reserves that finding's revision counter. Read-only,
  rejected, and unrelated proposals cannot consume or evade it.
- ✅ Reached limits create one durable resolution request: `ask_user` validates
  the pending human decision, `coordinator_decides` permits exactly one
  tool-free structured choice, and `stop` records a terminal outcome. Reassign
  and approach changes remain bounded by the available pool and hard ceilings.

Completion evidence (2026-07-26):

- Source: this change
- Verification: `npm run generate:contracts`; targeted Phase 4.3 backend tests
  and the repository verification suite (results recorded with this change).
- Artifacts/benchmarks: regenerated event/OpenAPI contracts and generated client types.
- Deferred/unavailable: release-shell and platform probes remain Phase 7 work; no new release-risk regression introduced.

### 4.4 Approval and grant engine (✅ Completed)

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

Completion evidence (2026-07-26):

- Source: Phase 4.4 approval-grant service, durable migration, scheduler and
  first-vertical-task enforcement, generated contracts, setup authority review,
  and Phase 4 security tests.
- Verification: focused approval/grant security tests, backend suite, contract
  generation, frontend type-check/test/build, documentation validation, and
  repository verification suite (results recorded with this change).
- Artifacts/benchmarks: policy-bound approval rows, migration 14, regenerated
  OpenAPI/session command/session event schemas and TypeScript clients.
- Deferred/unavailable: packaged release-shell and platform probes remain
  Phase 7 work; no release-risk regression introduced.

## Phase 5 — Roles, skills, models, and provider breadth

### 5.1 Agent definitions and capability routing (✅ Completed)

Deliverables:

- Version built-in Coordinator, Planner, Builder, Reviewer, Tester, and UI Agent
  templates.
- Support overrides and custom roles with declared capabilities, model binding,
  skill IDs, tool allowlist, permission profile, evidence contract, and language.
- Snapshot definitions into sessions so later edits do not alter active work.
- Route by capabilities and evidence requirements, using role names only for
  built-in UX defaults.

Completion evidence (2026-07-29):

- Source: this change
- Verification: `.agents/skills/argus-development/scripts/verify.sh docs`,
  `frontend`, and `backend` (documentation checks, generated contracts,
  type-check, 48 frontend tests/build, and 235 backend tests passed).
- Artifacts/benchmarks: migration 15, immutable agent-definition API and
  session snapshots, regenerated OpenAPI and TypeScript REST client types.
- Deferred/unavailable: packaged release-shell and platform probes remain
  Phase 7 work; no new release-risk regression introduced.

### 5.2 Local skill packages (✅ Completed)

Deliverables:

- Import and validate manifests, paths, content hashes, references, requested
  tools, and permissions.
- Display trust/capability review and keep imports disabled until enabled.
- Prevent traversal, symlink escape, mutable post-validation content, prompt
  injection from gaining tools, and session-policy escalation.
- Snapshot enabled skill content/version into assignment context metadata.

Completion evidence (2026-07-29):

- Source: this change
- Verification: `.agents/skills/argus-development/scripts/verify.sh all`
  (documentation checks, generated contracts, version/type checks, 49 frontend
  tests/build, 244 backend tests, backend import, and Cargo check passed).
- Artifacts/benchmarks: migration 16; immutable local package-file store;
  validated skill REST API and trust review UI; descriptor-scoped path handling;
  session-agent content snapshots and assignment attempt ID/version/hash metadata.
- Deferred/unavailable: packaged release-shell and platform probes remain
  Phase 7 work; no new release-risk regression introduced.

### 5.3 Native providers and credentials (✅ Completed)

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

Completion evidence (2026-07-29):

- Source: this change
- Verification: provider conformance and credential-profile tests, generated
  contracts, frontend type-check/test/build, backend import/test, Cargo check,
  documentation validation, and full repository verification (results recorded
  with this change).
- Artifacts/benchmarks: migration 17; generated OpenAPI/TypeScript provider
  profiles; Tauri OS credential-store commands and authenticated ephemeral
  sidecar leases; synthetic four-provider conformance fixtures.
- Deferred/unavailable: signed/installable Alpha shell and Windows/macOS/Linux
  native credential-store smoke probes require target clients and release
  credentials. They are pre-publish checks; this development-host result does
  not certify those targets.

## Phase 6 — Recovery, observability, and project completion workflow (✅ Completed; Beta publication is pre-publish)

### 6.1 Crash and reconnect recovery (✅ Completed)

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

Completion evidence (2026-07-29):

- Source: this change
- Verification: recovery/migration tests, frontend type-check/test/build,
  backend import/test, Cargo check, contract and documentation validation, and
  full repository verification (results recorded with this change).
- Artifacts/benchmarks: migration 18; checksummed bounded event snapshots;
  restart-recovery service; native 60-second sidecar-idle grace probe.
- Deferred/unavailable: packaged Windows/macOS/Linux crash, suspend/resume, and
  native credential-store restart smoke tests require target clients and are
  tracked by the pre-publish checklist; development-host checks do not certify
  those targets.

### 6.2 Diff review and acceptance (✅ Completed)

Deliverables:

- Provide file/tree diff, artifact evidence, test/review results, unmet gates,
  limit history, usage, and Coordinator summary.
- Let the user accept/apply changes through a policy-checked operation, reject
  them, export a patch, or start a follow-up assignment/session.
- Detect original project drift before apply and offer a safe conflict workflow.
- Clean up or retain worktrees according to an explicit user choice and status.

Completion evidence (2026-08-03):

- Source: this change
- Verification: acceptance/migration security tests, generated OpenAPI and
  TypeScript client validation, frontend type-check/test/build, backend
  import/test, Cargo check, contract and documentation validation, and full
  repository verification (results recorded with this change).
- Artifacts/benchmarks: migration 19; bounded acceptance review and patch
  endpoints; durable idempotent acceptance actions; original-project
  compare-and-swap checksum and policy/lease-gated apply workflow.
- Deferred/unavailable: packaged Windows/macOS/Linux apply and conflict smoke
  probes require target clients and are tracked by the pre-publish checklist;
  development-host checks do not certify those targets.

### 6.3 Local observability (✅ Completed)

Deliverables:

- Add structured redacted logs, runtime health, queue/lease status, provider
  latency, event lag, and usage diagnostics.
- Provide a user-exportable support bundle with configuration shapes and event
  summaries but no credentials, raw prompts by default, private reasoning, or
  project file contents without explicit selection.
- Add degraded-mode UI for provider outage, disk full, database lock, corrupted
  event, sidecar crash, and credential-store unavailability.

Completion evidence (2026-08-03):

- Source: this change
- Verification: full repository verification passed (documentation, version,
  frontend type-check/test/build, backend import/test, and Cargo check); 51
  frontend and 266 backend tests passed; generated OpenAPI/TypeScript contracts,
  benchmark-fixture tests, Cargo clippy/test, and focused observability/security
  regressions passed; clean focused diff check passed.
- Artifacts/benchmarks: bounded process-local redacted diagnostic log; generated
  `/runtime/health` and `/runtime/support-bundle` contracts; native
  credential-store availability probe; runtime/degraded-mode UI and redaction,
  pending-approval, support-bundle failure regression tests.
- Deferred/unavailable: `npm run benchmark:release` reported the native packaged
  Tauri-plus-sidecar release runner unavailable on this Linux development host.
  Signed/installable Windows, macOS, and Linux upgrade/install and target
  credential-store smoke probes are pre-publish gates; no development-host
  result certifies Beta distribution.

Phase 6 exit: an interrupted task recovers without duplicate mutation, and the
user can safely evaluate and apply or export the final isolated result.

## Phase 7 — Desktop integration and release hardening

### 7.1 Tauri and sidecar lifecycle (✅ Completed)

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

Completion evidence (2026-08-03):

- Source: this change
- Verification: full repository verification passed (documentation, version,
  frontend type-check/test/build, backend import/test, and Cargo check); 55
  frontend and 268 backend tests passed. Contract drift, Cargo fmt/clippy/test
  (4 lifecycle tests), independent reviewer re-review, read-only test review,
  frozen-sidecar authentication/shutdown smoke, and a release-equivalent Tauri
  no-bundle build also passed.
- Artifacts/benchmarks: PyInstaller 6.21.0 produced the
  `x86_64-unknown-linux-gnu` sidecar at 40,459,296 bytes with SHA-256
  `ad682a71e9edeefc476d84762902eb5712f9df217bb1f7ceece525f10649b1b6`;
  the generated composition report separates Argus code, base dependencies,
  Python runtime, and platform runtime and records excluded provider/dev groups.
- Deferred/unavailable: clean Windows/macOS client lifecycle probes, signed
  installers, real updater/uninstall/forced-close process-tree probes, and
  reference-hardware packaged benchmarks require publication environments. They
  are tracked by `PUBLISH_CHECKLIST.md`; this host result does not certify them.

### 7.2 Cross-platform quality (✅ Completed)

Deliverables:

- Support declared Windows, macOS, and Linux versions; document git/shell
  prerequisites and non-git fallback.
- Build natively in Windows x86_64, macOS arm64/x86_64, and Ubuntu 22.04 x86_64
  CI environments; probe current Ubuntu and Debian stable. Add Linux ARM64 only
  with a native runner and separate support gate.
- Generate unsigned release-equivalent NSIS, app bundle/DMG, AppImage, and Debian
  packages in native CI. Signing, notarization, and clean-client installation are
  pre-publish checks.
- Test path encoding, spaces, long paths, case behavior, line endings, executable
  bits, symlinks, and process cancellation deterministically. Test native
  keychain variants and sleep/resume before publishing.
- Automate keyboard semantics, axe structure, contrast, zoom, reduced motion,
  focus recovery, and large-timeline virtualization. Run real screen-reader and
  reference low-resource checks before publishing.
- Validate WebView2 bootstrap configuration and native-runner prerequisites on
  Windows, the declared WebKit/system version range on macOS, and
  WebKitGTK/glibc compatibility on Linux. Test real clean-client bootstrap
  before publishing.
- Keep deterministic performance fixtures and artifact attribution executable;
  run packaged measurements on each target's reference hardware before
  publishing.

Completion evidence (2026-08-03):

- Source: this change
- Verification: full repository verification passed (documentation, version,
  frontend type-check/test/build, backend import/test, and Cargo check); 57
  frontend and 268 backend tests passed. Platform-quality and accessibility
  suites, Python 3.12 backend isolation, generated-contract drift, Cargo
  fmt/clippy/test (4 tests), workflow lint, independent reviewer re-review, and
  read-only test review passed.
- Artifacts/benchmarks: a target-triple Linux frozen sidecar passed authenticated
  lifecycle smoke; a valid Debian package was produced at 45,115,790 bytes with
  SHA-256 `e77a12cd566b40a15e4f1abd25b0ec4a2c9d7bc1fdbc61061a42fb4c5f611ba9`;
  native CI declares Windows NSIS, macOS app/DMG, Linux AppImage/Debian, and
  current Ubuntu/Debian compatibility jobs. Desktop icons have valid native
  formats and the platform/accessibility contracts are executable in CI.
- Deferred/unavailable: clean supported-client installation, real keychain and
  sleep/resume variants, screen-reader pairings, signed/notarized artifacts, and
  reference-hardware packaged performance require target machines or release
  credentials and are tracked in `PUBLISH_CHECKLIST.md`. Local AppImage bundling
  on CachyOS is incompatible with linuxdeploy's RELR stripping; the declared
  Ubuntu 22.04 native CI environment owns that artifact.

### 7.3 Supply chain and release (✅ Completed)

Deliverables:

- Pin dependencies, generate SBOM, audit licenses/vulnerabilities, scan secrets,
  and verify reproducible clean builds where feasible.
- Configure signing/notarization, checksum, and versioned-release-note
  automation. Execute credential-dependent signing and clean-client
  install/upgrade/uninstall verification through the pre-publish checklist.
- Automate and validate the release transaction that selects a version from
  compatibility impact, synchronizes manifests, updates the changelog, and
  accepts only one immutable `vX.Y.Z` tag. Execute that version/tag transaction
  only after the pre-publish checklist passes.
- Add database/config backup before migrations and documented rollback/recovery.
- Publish threat model, privacy statement, vulnerability contact, known limits,
  and operator troubleshooting.

Completion evidence (2026-08-13):

- Source: this change
- Verification: full repository verification passed (27 documentation files,
  synchronized `0.1.0` manifests, 57 frontend tests and production build, 282
  backend tests, and Cargo check/fmt/clippy plus 4 Rust tests). Generated
  contracts, workflow actionlint, 14 focused backup/supply-chain tests, native
  sidecar smoke, npm/pip/Cargo vulnerability audits, full-history secret scan,
  and independent reviewer/read-only test re-review passed.
- Artifacts/benchmarks: deterministic CycloneDX 1.6 SBOM and license inventory
  covered 944 locked dependencies with zero forbidden or unresolved licenses;
  two clean frontend builds matched byte-for-byte. The Linux frozen sidecar was
  38,232,432 bytes with SHA-256
  `daa3b933d6bdb37859261190df76074ee3b3285e95abb74435b6f041ed680ca1`
  and passed authenticated startup/shutdown smoke.
- Deferred/unavailable: protected-environment signing/notarization,
  clean-client install/upgrade/uninstall, native backup ACL checks, and
  reference-hardware measurements require release credentials or target
  machines and remain publication-blocking in `PUBLISH_CHECKLIST.md`. No release
  version or tag was created because this is roadmap completion, not an approved
  release transaction. RustSec reports 17 reviewed warnings in Tauri's required
  Linux GTK3 dependency chain; known limits and upgrade ownership are documented.

Phase 7 exit: implementation, supply-chain automation, contracts, and standard
CI are ready to produce a release candidate. Publishing any candidate or stable
artifact additionally requires every applicable `PUBLISH_CHECKLIST.md` gate.

## Final definition of done

Argus roadmap implementation is finished for this product scope when all phase
gates pass and the following scenarios are automated:

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
10. The user reviews evidence and applies or exports an isolated diff from the
    desktop shell.

Signed clean-client distribution and native reference-hardware release budgets
are publication requirements in `PUBLISH_CHECKLIST.md`, not roadmap completion
criteria.

The legacy static session graph, transitional protocol types, simulator-only
claims, and undocumented approval paths must be removed before declaring the
product complete.
