# Frontend Guidance

These rules extend the root `AGENTS.md` for the React client under `src/`.

## Required context

- Read `docs/UX_SPEC.md` for visible behavior and accessibility.
- Read `docs/API.md` before changing transport, session state, or protocol reducers.
- Treat `backend/app/schemas/session_events.py` as authoritative for session events.

## Boundaries

- Components render and collect input; stores own client state; services own I/O and transport behavior.
- Keep the simulator and live transport on the same typed reducer path.
- Never use `any`. Validate untrusted wire, tool, and model data before it reaches UI state.
- Use tokens from `src/styles/tokens.css`; avoid hard-coded colors and one-off interaction patterns.
- Preserve keyboard access, focus behavior, reduced motion, and explicit empty/loading/reconnecting/error states.
- Do not persist credentials or sensitive session content in browser storage.

## Verification

Run `.agents/skills/argus-development/scripts/verify.sh frontend`. Protocol
changes also require backend, contract, simulator, and documentation checks from
the root guidance.
