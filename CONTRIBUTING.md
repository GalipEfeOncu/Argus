# Contributing to Argus

## Contribution model

Argus is local-first, transparent, and safety-conscious. Contributions must preserve these product invariants:

- The user can observe and control meaningful agent actions.
- Runtime policy enforcement is deterministic; prompts are not a security boundary.
- Secrets never enter source control, browser storage, event payloads, or logs.
- Frontend and backend protocol changes ship together.

## Setup

```bash
npm install
(cd backend && uv sync)
```

## Branches and commits

Use short-lived branches from `main`:

- `feat/<area>` — feature work
- `fix/<area>` — bug fixes
- `docs/<area>` — documentation-only changes
- `chore/<area>` — tooling and maintenance

Use Conventional Commits:

```text
feat(runtime): add ordered session event replay
fix(frontend): preserve pending approval state after reconnect
docs(protocol): define command idempotency requirements
```

## Required workflow

1. Read [AGENTS.md](AGENTS.md), the relevant product document, and nearby code before editing.
2. Keep a change within one coherent vertical slice.
3. Update the authoritative Pydantic contract before generated schema/types and frontend reducers.
4. Add or update tests for the behavior and failure mode.
5. Update the relevant documentation in the same pull request.
6. Review the final diff for unrelated changes and secrets.

## Verification

Run the checks relevant to the changed layer, then run the full check before merging:

```bash
npm run type-check
(cd backend && .venv/bin/python3 -c "import app.main; print('backend import OK')")
(cd src-tauri && cargo check)
```

As test tooling is introduced, the repository verification script becomes the required entry point:

```bash
.agents/skills/argus-development/scripts/verify.sh all
```

## Pull request checklist

- [ ] The change has a focused purpose and an understandable commit history.
- [ ] TypeScript, backend, and Tauri checks pass where applicable.
- [ ] Contracts, generated types, fixtures, and reducers are synchronized.
- [ ] New failure and permission paths are tested.
- [ ] API keys, tokens, paths, and user content are not leaked.
- [ ] Documentation and roadmap status are accurate.
- [ ] UI work covers loading, error, disconnected, and keyboard-accessible states.
