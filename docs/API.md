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
- `correlation_id` links an event to a client command, assignment, or tool execution.
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
| `assignment.created` / `handoff.created` | Coordinator or agent work delegation |
| `tool.requested` / `tool.started` / `tool.completed` | Visible tool lifecycle |
| `approval.requested` / `approval.resolved` | Human policy decision |
| `artifact.diff_updated` | File change or diff artifact update |
| `usage.updated` | Normalized tokens, cost, and duration |
| `error.created` | Recoverable or terminal failure |

### Client commands

Commands use `{ "command_id", "type", "payload" }`; `command_id` is the idempotency key.

| Type | Purpose |
| --- | --- |
| `message.send` | Send a human message; optional mention targets are explicit in payload |
| `session.start` / `session.pause` / `session.resume` / `session.cancel` | Control lifecycle |
| `participant.interrupt` | Stop one active participant |
| `approval.resolve` | Approve, reject, or grant scoped permission |
| `policy.update` | Update a session-scoped permission policy |

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
| `/artifacts` | Diffs, exports, and session files |

REST schemas are generated from FastAPI OpenAPI. Clients must not hand-maintain duplicate request/response interfaces.

## Compatibility rule

Any API or event change must update the Pydantic model, generated schema/types, frontend reducer, simulator fixture, backend tests, and this document in the same pull request.
