# Argus Architecture

## Purpose

Argus is a local-first desktop workspace for transparent multi-agent software development. It combines a Tauri desktop client, a React interface, and a local FastAPI runtime that coordinates model providers and project tools.

The product is not modeled as a fixed agent chain. A session is a shared, ordered collaboration room with a deterministic control plane and model-driven participants.

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

## Control plane and collaboration plane

The control plane owns facts that must be deterministic: event sequencing, policy checks, approvals, project locks, writer leases, cancellation, retries, timeouts, persistence, and recovery.

The collaboration plane contains the visible Coordinator and agents. They receive a bounded projection of the shared timeline, can create messages, request tools, assign work, hand off tasks, and produce artifacts. Model output never bypasses the control plane.

LangGraph may be used for an individual agent's tool loop and checkpointing. It is not the source of truth for session topology; the current static `Planner → Builder → Reviewer → Tester` graph will be replaced by the event-driven session runtime.

## Session lifecycle

```text
created → preparing → running ⇄ paused
                          ├→ waiting_approval ⇄ running
                          ├→ completed
                          ├→ cancelled
                          └→ failed
```

Each session has an append-only event log. The client receives a snapshot then events in increasing `sequence` order. On reconnect it requests events after its last confirmed sequence. Commands carry idempotency keys.

Different projects may run sessions concurrently. Only one mutating session can hold a project writer lock in the MVP. Within a session, read-only work may overlap while only one participant holds the writer lease.

## Participants, roles, and skills

Participants are `human`, `system`, `coordinator`, or `agent`. Built-in agent definitions provide a prompt, default skills, tool permissions, and suggested model capabilities. A user can override those values or create a custom capability-based role.

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

SQLite persists project metadata, sessions, immutable events, participant snapshots, approvals, assignments, artifacts, diffs, usage, and workspace metadata. The selected project remains the source of code; Argus stores orchestration metadata and isolated worktree state.

See [API.md](API.md) for protocol contracts, [SECURITY.md](SECURITY.md) for enforcement, and [UX_SPEC.md](UX_SPEC.md) for the visible product behavior.
