# Backend Guidance

These rules extend the root `AGENTS.md` for the FastAPI runtime under `backend/`.

## Required context

- Read `docs/ARCHITECTURE.md` and `docs/IMPLEMENTATION_SPEC.md` for ownership and runtime behavior.
- Read `docs/API.md` for external contracts and `docs/SECURITY.md` for tool, workspace, or credential changes.
- For REST/WebSocket changes, use `.agents/skills/argus-development/references/contract-checklist.md`.

## Boundaries

- Use async I/O for request, provider, persistence, and process boundaries.
- Validate all external input with Pydantic; keep event unions discriminated, ordered, and versioned.
- The deterministic runtime owns policy, ordering, idempotency, leases, cancellation, and persistence.
- An LLM prompt or LangGraph loop is never a policy or session-orchestration boundary.
- Scope filesystem, shell, search, and git actions to the active session workspace and treat tool arguments as untrusted.
- Never persist or emit provider credentials or private model reasoning.

## Verification

Run `.agents/skills/argus-development/scripts/verify.sh backend`. Contract
changes must also regenerate clients, update reducers and simulator fixtures,
cover failure/permission paths, and update `docs/API.md`.
