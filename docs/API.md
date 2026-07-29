# Argus API and Event Protocol

## Status

The canonical shared-room transport is available at
`/ws/sessions/{session_id}`. It validates v1 commands, commits an accepted
outcome before sending it, and replays ordered events after reconnect.
Accepted canonical events are broadcast to every currently connected client in
the session; a slow client is disconnected and can safely reconnect from its
last confirmed sequence.

## Base URLs

Development REST API: `http://127.0.0.1:8000`
Development WebSocket: `ws://127.0.0.1:8000`

## Event envelope

Every server event uses the following envelope:

```json
{
  "version": 1,
  "eventId": "evt_01...",
  "sessionId": "ses_01...",
  "sequence": 42,
  "timestamp": "2026-07-14T12:00:00Z",
  "type": "message.created",
  "actorId": "agent_builder",
  "correlationId": "cmd_01...",
  "payload": {}
}
```

- `sequence` is strictly increasing per session.
- `correlationId` links an event to a client command, assignment, or tool execution.
- Clients persist the highest applied sequence and request replay after reconnecting.
- Pydantic event and command models are authoritative and exposed as JSON Schema. `npm run generate:contracts` exports those schemas, FastAPI OpenAPI, and the frontend's generated TypeScript contracts.

## WebSocket

Connect to `/ws/sessions/{session_id}?after_sequence={n}`. The server first
emits `session.snapshot`, then a bounded ordered page of events after `n`.
Clients use the returned cursor through the timeline resource when more history
is needed, so a connection never hydrates an unbounded event log.

### Client projection and recovery

The client applies canonical events through one pure projection reducer.  It
keeps future sequence numbers in a bounded-in-time buffer, applies them only
after every predecessor, ignores byte-for-byte duplicate `eventId` values,
and requests a resync for a conflicting event ID, conflicting sequence,
malformed wire payload, or an unresolved sequence gap. A snapshot whose
`lastSequence` is older than the already applied sequence is stale and cannot
overwrite the projection.

The simulator and live WebSocket are transport implementations over that same
validated reducer boundary. Client commands enter a separate pending-command
collection keyed by `commandId`; a command is confirmed or cleared only by a
correlated server event. Retrying retains the original `commandId`.

The v1 snapshot payload currently supplies status and sequence metadata, not a
complete timeline projection. Its `lastSequence` therefore never advances the
client's applied-event cursor: ordered replay after the requested cursor
rebuilds timeline state. A later full snapshot revision must be applied
atomically with its projection data.

### Server event types

| Type | Purpose |
| --- | --- |
| `session.snapshot` | Current session projection for initial load or resync |
| `session.status_changed` | Lifecycle transition |
| `participant.status_changed` | Idle, working, waiting, paused, errored, or stopped state |
| `message.created` / `message.delta` / `message.completed` | Shared-room message streaming |
| `session.configuration_updated` | Audited future-facing team, gate, limit, or approval-policy update |
| `assignment.proposed` | Coordinator or specialist proposal awaiting scheduler validation |
| `assignment.created` / `assignment.started` | Accepted delegation and worker start |
| `assignment.completed` / `assignment.failed` / `assignment.cancelled` | Assignment terminal outcome and evidence |
| `handoff.created` | Persisted specialist result or follow-up proposal |
| `tool.requested` / `tool.started` / `tool.completed` | Visible tool lifecycle |
| `approval.requested` / `approval.resolved` | Human policy decision |
| `limit.warning` / `limit.reached` | Soft threshold or hard ceiling outcome |
| `decision.requested` / `decision.recorded` | Human or Coordinator limit-resolution decision |
| `gate.status_changed` | Required-role gate applicability and evidence state |
| `artifact.diff_updated` | File change or diff artifact update |
| `usage.updated` | Normalized tokens, cost, and duration |
| `error.created` | Recoverable or terminal failure |

### Client commands

Commands use `{ "commandId", "type", "payload" }`; `commandId` is the idempotency key.

| Type | Purpose |
| --- | --- |
| `message.send` | Send a human message; optional mention targets are explicit in payload |
| `session.start` / `session.pause` / `session.resume` / `session.cancel` | Control lifecycle |
| `participant.interrupt` | Stop one active participant |
| `approval.resolve` | Approve, reject, or grant scoped permission |
| `session.configuration.update` | Update future team, gate, limit, or approval settings with an expected configuration version |
| `decision.resolve` | Resolve a pending human limit or partial-completion decision |

### Canonical target wire shapes

The target Pydantic unions in `backend/app/schemas/session_events.py` and
`backend/app/schemas/session_commands.py` are the normative machine-readable
definitions. They reject unknown fields at every modeled level, serialize using
camelCase, and use `type` as their discriminator. The live WebSocket handler
at `/ws/sessions/{sessionId}` validates and emits these canonical shapes; the
client applies both replayed and live events through the same reducer used by
the event simulator.

All server-event branches share the envelope shown above. `eventId`,
`sessionId`, `actorId`, and optional `correlationId` are non-empty opaque IDs;
`sequence` is a non-negative integer and `timestamp` is required ISO 8601 text
with a `T` separator and UTC (`Z`) or numeric-offset timezone; numeric Unix
timestamps and timezone-naive values are invalid.
All client-command branches share a non-empty opaque `commandId`, which is the
idempotency key. Strings labelled *summary* are user-visible redacted summaries,
never provider credentials or private model reasoning. Lists are bounded by the
schema and file payloads carry metadata rather than an unbounded inline diff.

The following payload fields make each target union branch unambiguous. Every
identifier field is an opaque ID except `filePath`, which is a relative artifact
path. `filePath` rejects POSIX, Windows-drive, and UNC absolute forms and any
`..` traversal segment without resolving a filesystem path. Optional fields may
be omitted or set to `null` where the schema allows.

| Event type | Required payload fields | Optional payload fields |
| --- | --- | --- |
| `session.snapshot` | `status`, `lastSequence` | — |
| `session.status_changed` | `status` | `reasonSummary` |
| `participant.status_changed` | `participantId`, `participantKind`, `status` | `actionSummary` |
| `message.created` | `messageId`, `authorId`, `authorKind`, `content` | `mentionIds`, `streaming` |
| `message.delta` | `messageId`, `delta` | — |
| `message.completed` | `messageId` | — |
| `session.configuration_updated` | `configurationVersion`, `previousPolicyHash`, `policyHash`, `changedFields` | — |
| `assignment.proposed` | `proposalId`, `assigneeAgentId`, `objective`, `acceptanceCriteria`, `operationClass`, `reasonSummary` | `parentId`, `requestedCapabilities`, `requestedTools` |
| `assignment.created` | `assignmentId`, `proposalId`, `assigneeAgentId`, `configurationVersion`, `policyHash`, `operationClass` | — |
| `assignment.started` | `assignmentId`, `assigneeAgentId` | — |
| `assignment.completed` | `assignmentId`, `status`, `outputSummary` | `evidence` |
| `assignment.failed` | `assignmentId`, `failureCode`, `failureSummary`, `recoverable` | — |
| `assignment.cancelled` | `assignmentId`, `reasonSummary` | — |
| `handoff.created` | `handoffId`, `sourceAssignmentId`, `summary` | `targetAgentId`, `artifactIds` |
| `tool.requested` | `toolExecutionId`, `assignmentId`, `toolName`, `operationClass`, `requestSummary` | — |
| `tool.started` | `toolExecutionId`, `assignmentId`, `toolName` | — |
| `tool.completed` | `toolExecutionId`, `assignmentId`, `status`, `resultSummary`, `durationMs` | `artifactIds` |
| `approval.requested` | `approvalId`, `capability`, `scopeSummary` | `assignmentId` |
| `approval.resolved` | `approvalId`, `resolution` | `grantId`, `reasonSummary` |
| `limit.warning`, `limit.reached` | `counter`, `scopeId`, `current`, `threshold`, `hard`, `resolution` | `fingerprint`, `occurrenceCount` |
| `decision.requested` | `decisionId`, `scopeId`, `choices`, `reasonSummary` | `purpose`, `unmetRequirements` |
| `decision.recorded` | `decisionId`, `choice`, `reasonSummary` | — |
| `gate.status_changed` | `gateId`, `role`, `status` | `evidence` |
| `artifact.diff_updated` | `artifactId`, `filePath`, `additions`, `deletions`, `byteLength` | `assignmentId`, `truncated` |
| `usage.updated` | `scopeId`, `inputTokens`, `outputTokens`, `normalizedCost`, `durationMs` | — |
| `error.created` | `errorId`, `code`, `summary`, `recoverable` | `relatedId` |

`evidence` entries contain `kind`, a redacted `summary`, optional `artifactIds`,
and optional structured `data`. Valid session statuses are `created`, `preparing`, `running`,
`paused`, `waiting_approval`, `waiting_decision`, `completed`,
`completed_partial`, `cancelled`, and `failed`; participant statuses are `idle`,
`working`, `waiting`, `paused`, `errored`, and `stopped`. Assignment operation
classes are `read_only` and `mutating`.

| Command type | Required payload fields | Optional payload fields |
| --- | --- | --- |
| `message.send` | `content` | `mentionIds` |
| `session.start`, `session.pause`, `session.resume` | none (empty object) | — |
| `session.cancel` | none | `reasonSummary` |
| `participant.interrupt` | `participantId`, `reasonSummary` | — |
| `approval.resolve` | `approvalId`, `resolution` | `grantCapabilities`, `scopeSummary`, `grantScope`, `grantDurationSeconds` |
| `session.configuration.update` | `expectedConfigurationVersion`, non-empty `patch` | `confirmConsequences` |
| `decision.resolve` | `decisionId`, `choice` | `reasonSummary` |

For `approval.resolve`, `resolution` is `approve`, `reject`, or `grant`; a
grant requires non-empty bounded `grantCapabilities` and a non-empty
human-readable `scopeSummary`. `approve` and `reject` must not carry
`grantCapabilities`, so ignored capabilities cannot widen a permission. A
grant can be `once`, `scope`, or `session` scoped and always receives a durable
expiry; its capability must exactly match its persisted request, its scope
cannot widen that request, and its policy hash must still match at use time.
A missing, resolved, revoked, expired, or policy-stale approval ID is rejected.
configuration `patch` may set `availableAgentIds`, `requiredRoleRules`, any
`executionLimits` field, `approvalBehavior`, `permissionProfile`,
`preauthorizedCapabilities`, `capabilityOverrides`, or `limitResolution`; a capability-based required-role rule
includes `capability`, while other rule applicability values must omit it.
Decision choices are `reassign`, `change_approach`, `deliver_partial`, or
`stop`. Limit resolution is `ask_user`, `coordinator_decides`, or `stop`.

### First isolated vertical task

For the current provider-neutral reference task, `session.start` persists the
Coordinator handoff and then requests one bounded `workspace.write` grant.
After a human `approval.resolve` command with `resolution: "grant"`, the
Builder writes only inside the session worktree or snapshot, records the tool
lifecycle and diff artifact, and completes with evidence. These worker events
are appended before live fan-out, so reconnect uses the same ordered replay.
Pause, resume, cancel, and human messages remain normal canonical commands;
an accepted cancellation is serialized with an in-flight workspace mutation.
Rejected commands are emitted as correlated `error.created` events rather than
an out-of-band WebSocket payload, allowing clients to clear pending state.

### Approval and authority evaluation

The backend evaluates every capability request in this order: non-bypassable
denial, canonical workspace scope, permission profile, capability override,
stored policy-bound grant, then approval behavior. The most restrictive result
wins. `ask_each_time` never reuses a grant; `deny_interactive` never creates a
prompt and returns a visible denial for ungranted work. `preauthorize_session`
creates auditable, expiring session grants at start after the required
acknowledgement. Coordinator output cannot resolve an approval or manufacture a
grant.

## Session configuration contract

`POST /sessions` accepts durable configuration. IDs below reference existing
project and agent-definition resources; secrets are never accepted here. Agent
definitions are resolved before the session is created, so each session agent
contains a complete immutable copy rather than a live reference to editable
role settings.
The backend stores a fresh immutable session-agent snapshot for every supplied
agent and returns those session-snapshot IDs in normalized `availableAgentIds`.

```json
{
  "projectId": "prj_01...",
  "goal": "Add rate limiting and verify it",
  "coordinatorAgentId": "agd_coordinator",
  "agents": [
    { "id": "agd_coordinator", "role": "coordinator", "agentDefinitionId": "builtin.coordinator.v1" },
    { "id": "agd_builder", "role": "builder", "agentDefinitionId": "builtin.builder.v1" },
    { "id": "agd_reviewer", "role": "reviewer", "agentDefinitionId": "builtin.reviewer.v1" },
    { "id": "agd_tester", "role": "tester", "agentDefinitionId": "builtin.tester.v1" }
  ],
  "configuration": {
    "availableAgentIds": ["agd_builder", "agd_reviewer", "agd_tester"],
    "requiredRoleRules": [
      {
        "id": "gate_review",
        "role": "reviewer",
        "applicability": "when_changes",
        "successEvidence": "approved_review",
        "minimumCompletions": 1
      }
    ],
    "executionLimits": { "maxSessionTokens": 500000 },
    "approvalPolicy": {
      "permissionProfile": "autonomous",
      "behavior": "preauthorize_session",
      "preauthorizedCapabilities": ["workspace.read", "workspace.write", "test.run"],
      "limitResolution": "coordinator_decides"
    },
    "workspacePolicy": { "mode": "worktree" },
    "acknowledgements": ["autonomous_permissions"]
  }
}
```

### Agent definitions

`GET /agent-definitions/` returns the versioned built-in Coordinator, Planner,
Builder, Reviewer, Tester, and UI Agent templates plus immutable user-created
definitions. `POST /agent-definitions/` creates either a `builtin_override` or
a `custom` definition; definitions are append-only, so editing means creating
a new version and can never change an active session.

Every definition declares its `role`, `systemPrompt`, non-secret
`modelBinding`, `capabilities`, `skillIds`, `toolAllowlist`,
`permissionProfile`, `evidenceKinds`, `evidenceSchema`, and `outputLanguage`.
Custom definitions require an evidence schema from the restricted subset
described below. Built-in template identities are runtime-managed and cannot be
overwritten. Built-in overrides inherit their base role's deterministic evidence
validator; custom roles must declare at least one non-built-in evidence kind and
a supported schema. A session may narrow capabilities, skills, tools, or the
role permission profile, but it cannot expand any of them or replace an
evidence contract. Requested assignment tools outside the session-agent
allowlist are rejected before dispatch; the current executable reference worker
also checks its immutable assignment snapshot immediately before tool use.

Routing checks declared capabilities and the evidence kinds a session agent can
produce. A role name is a built-in display/default convenience, not an
authorization grant: required-gate routing additionally matches each rule's
`requiredCapabilities` and `successEvidence`.

Every numeric maximum except `maxSessionCost` is an integer greater than or
equal to zero or `null`; `maxSessionCost` is a non-negative decimal amount or
`null`. `0` prohibits the counted action; `null` removes the user ceiling but remains
subject to runtime resource and safety guards. `softWarningRatio` is greater
than zero and at most one. The server returns a normalized snapshot,
`configurationVersion`, policy hash, defaults resolved by the backend, and
acknowledgement descriptors. `direct_write` requires the limited-rollback
acknowledgement; Autonomous and Expert unrestricted profiles require their
respective permission acknowledgements before creation.

### Budget and usage accounting

The deterministic budget service persists counters by their natural scope:
session (`tokens`, normalized `cost`, active wall-clock time, and parallel
read-only work), assignment (attempts, model iterations, and tool calls), and
finding (accepted revision work). Counters and reservations survive a restart.
Before dispatch, the scheduler atomically reserves the assignment attempt and
any read-only capacity slot with the assignment state transition. A reservation
that never starts may be returned; a started attempt remains consumed, so a
retry never receives a free budget unit. Parallel read-only capacity is released
only after its assignment becomes terminal.

At the configured ratio, the server emits one `limit.warning` for a counter
scope. A request that would exceed a finite ceiling first appends
`limit.reached` and then is not started. Internal writer leases and other
resource guards are separate enforcement mechanisms and are never relaxed by
an unlimited (`null`) user limit.

`usage.updated.normalizedCost` may be `null` when a provider cannot supply a
normalizable cost. `costUncertainty` is `exact`, `estimated`, or `unavailable`;
clients must present the value as an uncertainty rather than treating a missing
cost as zero. A later provider correction replaces the attempt's normalized
usage and adjusts durable token/cost totals by its delta. Wall-clock accounting
uses only runnable time: paused, approval-waiting, decision-waiting, and
terminal intervals do not consume it.

Validation rejects duplicate agents, a Coordinator in `availableAgentIds`, a
required rule with no eligible available agent, unsupported evidence types,
unsafe preauthorizations, and limits that contradict the selected workspace or
permission profile. Rejections use stable `detail.code` values such as
`duplicate_agent_id`, `required_role_unavailable`, `unsafe_preauthorization`,
and `acknowledgement_required`.

### Required-role rule

`applicability` is `always`, `when_changes`, or `when_capability_used`.
Capability-based rules also include `capability`. `successEvidence` is a
versioned role-specific evidence kind such as `approved_review`,
`passing_test_run`, `accepted_plan`, or a registered custom-role evidence kind.
`requiredCapabilities` optionally narrows eligible evidence providers further.
The scheduler alone changes a gate to satisfied after validating assignment
evidence.

Planner rules may declare `acceptanceFields`; each named field must be present
in the structured plan evidence. Built-in evidence is deterministic: Planner
requires non-empty plan steps; Builder/UI Agent requires a diff artifact or an
explicit verified no-change result; Reviewer requires an approved review; and
Tester requires a named command, a zero exit code, and at least one test.
Reviewer and Tester evidence includes `workspaceRevision`, which must match the
active workspace checksum. A later mutation invalidates their older evidence.
A custom required role must snapshot an `evidenceSchema` contract on its session
agent; its evidence `data` must satisfy it. The current supported JSON-Schema
subset is deliberately strict: `type`, `enum`, object `required`/`properties`/
`additionalProperties`, array `items`/`minItems`, string `minLength`, and numeric
`minimum`; unsupported keywords are rejected when the session is configured.

### Configuration updates

`session.configuration.update` contains `expectedConfigurationVersion` and a
partial patch. The command is rejected with `stale_configuration_version` on a
version conflict. Accepted changes append an immutable version and apply only
to future dispatches. Removing an active agent or reducing a permission emits
a recoverable `configuration_preview_required` consequence preview unless
`confirmConsequences` is true; confirmation interrupts affected active
assignments in the same durable command outcome. Counters never decrease and
completed evidence remains auditable. Confirming a consequence preview is a
new command and therefore uses a new `commandId`; retransmitting either the
preview request or the confirmation keeps that command's original ID.

## Coordinator action contract

The Coordinator worker returns exactly one strict, structured action for each
accepted human goal or specialist result. This is an internal runtime contract,
not a client command: the deterministic runtime validates it before it creates
any scheduler work.

| Action | Required visible fields | Runtime effect |
| --- | --- | --- |
| `assignments` | concise `routingSummary`, one or more proposals with ID, optional parent, objective, criteria, operation class, requested budget/capabilities/tools, and reason | Proposes dynamic specialist work; every assignee, capability, and tool is validated against the current available pool and immutable agent allowlist. |
| `wait` | concise `routingSummary` | Leaves the session waiting for relevant work or evidence. |
| `ask_user` | concise `routingSummary` and `question` | Requests a visible human decision. |
| `final` | concise `finalSummary` and non-empty `evidenceReferences` | May finish only after deterministic required-gate validation. |
| `partial` | concise `finalSummary`, unmet requirements, optional evidence references | Describes a bounded partial outcome; it does not claim success. |
| `stop` | concise `finalSummary` and reason | Ends this Coordinator cycle using the configured decision policy. |

Unknown fields and every other action type are rejected. In particular, a
Coordinator action cannot grant permissions, alter session configuration,
modify limits or pool membership, create gate evidence, or mark a gate
satisfied. A malformed or unauthorized response receives one correction
request; a second invalid response stops the cycle and follows the configured
limit-resolution policy.

A `partial` action creates a visible `decision.requested` event with purpose
`partial_completion`, including its unmet requirements, and puts the session in `waiting_decision`. Only a human
`decision.resolve` for that persisted decision can transition the session to
`completed_partial`; it never transitions to `completed`.

An unmentioned `message.send` is persisted as a pending instruction for the
mandatory Coordinator. Explicit mention IDs resolve to exactly one immutable
session participant and are persisted as pending participant instructions for
the scheduler. The visible human message remains the shared-room record, while
the instruction queue avoids hidden or in-memory-only routing.

## Assignment contract

An assignment proposal contains `proposalId`, `assigneeAgentId`, `parentId`,
`objective`, acceptance criteria, requested operation class (`read_only` or
`mutating`), requested budget, required capabilities, and reason summary. The
scheduler accepts it only when:

1. the assignee is in the current available pool and is not already terminal;
2. declared capabilities cover the request;
3. session and assignment budgets have remaining capacity;
4. required permissions or grants exist;
5. concurrency, project lock, and writer-lease rules allow dispatch.

Accepted assignments receive a server ID and immutable configuration/policy
versions. Results contain a status, concise output, structured evidence,
artifact references, usage, and normalized failure signature. Model prose alone
cannot satisfy a required gate.

## Limit and decision payloads

`limit.warning` and `limit.reached` identify `counter`, `scopeId`, `current`,
`threshold`, `hard`, and the policy-selected resolution. Repeated-review and
no-progress detectors additionally include stable redacted fingerprints and
occurrence counts.

With `coordinator_decides`, the runtime creates one decision-only Coordinator
invocation with no mutation tools. Its allowed response is a discriminated
choice: `reassign`, `change_approach`, `deliver_partial`, or `stop`. The
scheduler validates remaining budgets and pool membership before recording the
decision. A hard ceiling cannot be extended by this response. With `ask_user`,
the session enters `waiting_decision`; with `stop`, the affected assignment is
ended immediately.

Loop signals are a durable projection rather than raw event-text scans. Review
findings, failure signatures, and workspace/diff no-progress checks are
normalized to redacted SHA-256 fingerprints; the original review prose and tool
output are not stored by this mechanism. A mutating follow-up may identify only
a previously observed finding fingerprint. Its revision reservation is made as
the proposal is accepted, so a rejected, read-only, or unrelated proposal cannot
consume or bypass that finding's revision budget. Limit-resolution requests are
also durable and tied to the source `limit.reached` event; replayed, stale, or
unrequested human decisions are rejected.

## REST resources

The REST API manages durable configuration; real-time execution uses WebSocket commands and events.

| Resource | Responsibilities |
| --- | --- |
| `/health` | Runtime health and version |
| `/projects` | Register, validate, and list local projects |
| `/sessions` | Create, list, inspect, archive, and delete sessions |
| `/agent-definitions` | Built-in templates, overrides, and custom roles |
| `/skills` | List, import, validate, enable, and assign local skills |
| `/providers` | Provider metadata, credential references, validation, and model discovery |
| `/policies` | Permission profiles and session overrides |
| `/session-presets` | Built-in and user-saved team, limit, gate, and approval presets |
| `/artifacts` | Diffs, exports, and session files |

`GET /sessions/{sessionId}/timeline?after_sequence={n}&limit={n}` returns at
most 200 canonical events and exposes `nextAfterSequence` when more rows exist.
`GET /sessions/{sessionId}/artifacts?cursor={createdAtMs}:{id}&limit={n}`
returns at most 100 artifact summaries and exposes `nextCursor`. Both queries
use their session cursor indexes and return metadata only; neither endpoint
hydrates artifact bodies or the complete event log.

`GET /sessions/{sessionId}/configuration` returns the latest normalized,
immutable configuration snapshot after process restart.

### Local skills

`POST /skills/import` accepts `{ "sourcePath": "<absolute local directory>" }`.
The directory must contain a schema-version-1 `skill.json`; the runtime accepts
only UTF-8 regular files, rejects parent traversal and every symbolic link, and
copies validated content into SQLite. `GET /skills/` exposes the manifest,
content hash, requested tools and permissions, and review state. Imported
packages start as `review_required` and disabled; `POST /skills/{skillId}/enable`
with `{ "enabled": true }` records explicit enablement.

An enabled skill may be selected in a session agent's `skillIds` only when its
declared tools are already in that immutable agent's tool allowlist and its
requested permissions are already in the agent's capabilities. The server
snapshots the stored package content, version, and hash into `session_agents`;
it never re-reads the mutable source directory for an active session.

REST schemas are generated from FastAPI OpenAPI. Clients must not hand-maintain duplicate request/response interfaces.

### Project registration

`POST /projects` registers an existing local directory before it can be used by
a session. The request is `{ "path": "…", "displayName": "optional" }`.
The backend resolves and persists the canonical path, rather than preserving a
user-supplied spelling. The response includes a stable project ID and git
inspection metadata: repository root and head, dirty state, nested repository
paths, symbolic-link presence, and filesystem case-sensitivity.

Registration rejects non-directories, filesystem roots, paths that cannot be
inspected safely, and a subdirectory of a git repository. `GET /projects`
returns those durable registrations. Project registration never copies or
modifies project files except for an immediately removed case-sensitivity probe.

Workspace creation is owned by the session service. `POST /sessions` accepts an
optional `workspace_mode` (`worktree`, `snapshot`, or `direct_write`) and
`acknowledge_direct_write: true`; omitting the mode selects worktree for git
projects and snapshot otherwise. `worktree` creates an
`argus/{sessionId}` branch below the managed Argus workspace root; non-git
projects use a managed copy-on-write `snapshot`. The backend rejects
`direct_write` without that separate, explicit acknowledgement and records the
choice in workspace audit history. Each accepted mutation records a content
checksum and a bounded diff-summary artifact.

## Generated contract artifacts

`npm run generate:contracts` is the only regeneration command. It exports the
canonical Pydantic adapters to `contracts/session-events.schema.json` and
`contracts/session-commands.schema.json`, exports the FastAPI application to
`contracts/openapi.json`, and generates the corresponding TypeScript files in
`src/types/generated/`. Generated files carry a provenance marker and must not
be edited by hand.

## Compatibility rule

Any API or event change must update the Pydantic model, generated schema/types, frontend reducer, simulator fixture, backend tests, and this document in the same pull request.
