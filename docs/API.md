# Argus API and Event Protocol

## Status

This is the target contract for the shared-room runtime. Existing endpoints and WebSocket handlers are transitional and will be migrated to this protocol before they are treated as stable.

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
- Pydantic event models are authoritative and exposed as JSON Schema. The frontend's typed contract mirrors this schema; automated type generation is the next contract-tooling step.

## WebSocket

Connect to `GET /ws/sessions/{session_id}?after_sequence={n}`. The server first emits `session.snapshot`, then all events after `n`.

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

## Session configuration contract

`POST /sessions` accepts durable configuration. IDs below reference existing
project and agent-definition resources; secrets are never accepted here.

```json
{
  "projectId": "prj_01...",
  "goal": "Add rate limiting and verify it",
  "coordinatorAgentId": "agd_coordinator",
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
  "executionLimits": {
    "maxRevisionsPerFinding": 3,
    "maxAssignmentAttempts": 8,
    "maxModelIterationsPerAssignment": 20,
    "maxToolCallsPerAssignment": 100,
    "maxSessionTokens": 500000,
    "maxSessionCost": null,
    "maxWallClockSeconds": 14400,
    "maxParallelReadOnlyAssignments": 3,
    "softWarningRatio": 0.8
  },
  "approvalPolicy": {
    "permissionProfile": "autonomous",
    "behavior": "preauthorize_session",
    "preauthorizedCapabilities": [
      "workspace.read",
      "workspace.write",
      "test.run"
    ],
    "limitResolution": "coordinator_decides"
  },
  "workspacePolicy": { "mode": "worktree" }
}
```

Every numeric maximum is an integer greater than or equal to zero or `null`.
`0` prohibits the counted action; `null` removes the user ceiling but remains
subject to runtime resource and safety guards. `softWarningRatio` is greater
than zero and at most one. The server returns a normalized snapshot,
`configurationVersion`, policy hash, defaults resolved by the backend, and any
required acknowledgement descriptors.

Validation rejects duplicate agents, a Coordinator in `availableAgentIds`, a
required rule with no eligible available agent, unsupported evidence types,
unsafe preauthorizations, and limits that contradict the selected workspace or
permission profile. Rejections use stable machine-readable error codes.

### Required-role rule

`applicability` is `always`, `when_changes`, or `when_capability_used`.
Capability-based rules also include `capability`. `successEvidence` is a
versioned role-specific evidence kind such as `approved_review`,
`passing_test_run`, `accepted_plan`, or a registered custom-role evidence kind.
The scheduler alone changes a gate to satisfied after validating assignment
evidence.

### Configuration updates

`session.configuration.update` contains `expectedConfigurationVersion` and a
partial patch. The command is rejected on version conflict. Accepted changes
increment the version and apply only to future dispatches. Removing an active
agent or reducing a permission returns a `consequences` preview unless
`confirmConsequences` is true; once confirmed, the scheduler interrupts work
that is no longer valid. Counters never decrease and completed evidence remains
auditable.

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

REST schemas are generated from FastAPI OpenAPI. Clients must not hand-maintain duplicate request/response interfaces.

## Compatibility rule

Any API or event change must update the Pydantic model, generated schema/types, frontend reducer, simulator fixture, backend tests, and this document in the same pull request.
