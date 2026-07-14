# Argus Repository Guidance

## Product invariants

Argus is a local-first, transparent multi-agent workspace. Preserve these rules in every change:

- The shared timeline is the user-visible source of collaboration truth.
- A visible Coordinator explains assignments and handoffs; deterministic services enforce policy, state, ordering, and tool boundaries.
- Never expose provider credentials or private model reasoning in UI, logs, events, exports, or persistence.
- Worktree isolation and balanced approval policy are the default; more permissive modes require explicit user intent.
- Built-in roles and skills are customizable; custom roles are capability-based.

Read `docs/PRODUCT.md`, `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/UX_SPEC.md`, and `docs/SECURITY.md` before changing their corresponding area.

## Repository boundaries

- `src/` — React 19 client; keep UI state and protocol reducers typed.
- `backend/` — FastAPI runtime; use async I/O and Pydantic at external boundaries.
- `src-tauri/` — native bridge and sidecar lifecycle; use least privilege.
- `docs/` — product and implementation contracts, not aspirational feature claims.
- `.agents/skills/argus-development/` — reusable Codex workflow for this repository.

Do not reintroduce a fixed agent pipeline as product behavior. LangGraph may support a single agent loop but may not own session orchestration state.

## Contract-first changes

For REST or WebSocket behavior:

1. Update the authoritative backend model.
2. Regenerate schema/client types.
3. Update frontend reducers and the event simulator.
4. Add success, reconnect/order, malformed-input, and permission-path tests.
5. Update `docs/API.md`.

Use ordered, versioned events and idempotent client commands. Do not hand-maintain duplicate protocol types.

## Implementation rules

- Prefer focused vertical slices over broad partial rewrites.
- Do not use `any` in TypeScript; use explicit types or `unknown` with validation.
- Keep React components small and accessible; use design tokens instead of hard-coded colors.
- Keep stores for state, services for I/O/business behavior, and components for rendering.
- Scope every filesystem or shell action to the active session workspace.
- Treat model output as untrusted input.
- Do not store API keys in Zustand persistence, localStorage, SQLite, test fixtures, or logs.

## Validation

Run the relevant commands after changes:

```bash
npm run type-check
(cd backend && .venv/bin/python3 -c "import app.main; print('backend import OK')")
(cd src-tauri && cargo check)
```

Use `.agents/skills/argus-development/scripts/verify.sh` for scoped or complete validation when available. Do not claim a feature is complete unless its implementation, tests, and documentation agree.
