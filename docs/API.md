# Argus API and Event Protocol

## Status

The canonical shared-room transport is available at
`/ws/sessions/{session_id}`. It validates v1 commands, commits an accepted
outcome before sending it, and replays ordered events after reconnect. The
older singular `/ws/session/{session_id}` agent-graph stream remains
transitional until the scheduler is migrated to the durable control plane.
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
camelCase, and use `type` as their discriminator. The existing live WebSocket
handler is transitional and does not yet emit or consume these shapes.

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
| `assignment.proposed` | `proposalId`, `assigneeAgentId`, `objective`, `acceptanceCriteria`, `operationClass`, `reasonSummary` | `parentId`, `requestedCapabilities` |
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
| `decision.requested` | `decisionId`, `scopeId`, `choices`, `reasonSummary` | — |
| `decision.recorded` | `decisionId`, `choice`, `reasonSummary` | — |
| `gate.status_changed` | `gateId`, `role`, `status` | `evidence` |
| `artifact.diff_updated` | `artifactId`, `filePath`, `additions`, `deletions`, `byteLength` | `assignmentId`, `truncated` |
| `usage.updated` | `scopeId`, `inputTokens`, `outputTokens`, `normalizedCost`, `durationMs` | — |
| `error.created` | `errorId`, `code`, `summary`, `recoverable` | `relatedId` |

`evidence` entries contain `kind`, a redacted `summary`, and optional
`artifactIds`. Valid session statuses are `created`, `preparing`, `running`,
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
| `approval.resolve` | `approvalId`, `resolution` | `grantCapabilities`, `scopeSummary` |
| `session.configuration.update` | `expectedConfigurationVersion`, non-empty `patch` | `confirmConsequences` |
| `decision.resolve` | `decisionId`, `choice` | `reasonSummary` |

For `approval.resolve`, `resolution` is `approve`, `reject`, or `grant`; a
grant requires non-empty bounded `grantCapabilities` and a non-empty
human-readable `scopeSummary`. `approve` and `reject` must not carry
`grantCapabilities`, so ignored capabilities cannot widen a permission. A
configuration `patch` may set `availableAgentIds`, `requiredRoleRules`, any
`executionLimits` field, `approvalBehavior`, `permissionProfile`,
`preauthorizedCapabilities`, or `limitResolution`; a capability-based required-role rule
includes `capability`, while other rule applicability values must omit it.
Decision choices are `reassign`, `change_approach`, `deliver_partial`, or
`stop`. Limit resolution is `ask_user`, `coordinator_decides`, or `stop`.

## Session configuration contract

`POST /sessions` accepts durable configuration. IDs below reference existing
project and agent-definition resources; secrets are never accepted here.
The backend stores a fresh immutable session-agent snapshot for every supplied
agent and returns those session-snapshot IDs in normalized `availableAgentIds`.

```json
{
  "projectId": "prj_01...",
  "goal": "Add rate limiting and verify it",
  "coordinatorAgentId": "agd_coordinator",
  "agents": [
    { "id": "agd_coordinator", "role": "coordinator" },
    { "id": "agd_builder", "role": "builder", "capabilities": ["workspace.write"] },
    { "id": "agd_reviewer", "role": "reviewer", "capabilities": ["workspace.read"] },
    { "id": "agd_tester", "role": "tester", "capabilities": ["test.run"] }
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

Every numeric maximum except `maxSessionCost` is an integer greater than or
equal to zero or `null`; `maxSessionCost` is a non-negative decimal amount or
`null`. `0` prohibits the counted action; `null` removes the user ceiling but remains
subject to runtime resource and safety guards. `softWarningRatio` is greater
than zero and at most one. The server returns a normalized snapshot,
`configurationVersion`, policy hash, defaults resolved by the backend, and
acknowledgement descriptors. `direct_write` requires the limited-rollback
acknowledgement; Autonomous and Expert unrestricted profiles require their
respective permission acknowledgements before creation.

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
The scheduler alone changes a gate to satisfied after validating assignment
evidence.

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
be edited by hand. The legacy WebSocket transport types remain separate and
transitional until the runtime migration consumes the canonical envelope.

## Compatibility rule

Any API or event change must update the Pydantic model, generated schema/types, frontend reducer, simulator fixture, backend tests, and this document in the same pull request.
