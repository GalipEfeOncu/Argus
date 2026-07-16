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

1. Read [AGENTS.md](AGENTS.md), the [documentation index](docs/README.md), the
   applicable directory guidance, and nearby code before editing.
2. Identify the source of truth and affected contract, persistence, UI,
   workspace, and permission boundaries.
3. Keep the change within one coherent vertical slice.
4. Update the authoritative Pydantic contract before generated schema/types and frontend reducers.
5. Add or update tests for success and relevant failure or permission paths.
6. Update the relevant documentation in the same pull request.
7. Run scoped verification, then review the final diff for unrelated changes,
   secrets, stale claims, and generated-file drift.

When multiple coding agents collaborate, assign independently verifiable
boundaries with explicit acceptance criteria and path ownership. Avoid multiple
agents editing the same contract or file; the coordinating agent owns integration
and final verification.

## Verification

Run the checks relevant to the changed layer, then run the full check before merging:

```bash
.agents/skills/argus-development/scripts/verify.sh docs
.agents/skills/argus-development/scripts/verify.sh frontend
.agents/skills/argus-development/scripts/verify.sh backend
.agents/skills/argus-development/scripts/verify.sh tauri
.agents/skills/argus-development/scripts/verify.sh all
```

## Pull request checklist

- [ ] The change has a focused purpose and an understandable commit history.
- [ ] TypeScript, backend, and Tauri checks pass where applicable.
- [ ] Contracts, generated types, fixtures, and reducers are synchronized.
- [ ] New failure and permission paths are tested.
- [ ] API keys, tokens, paths, and user content are not leaked.
- [ ] Documentation and roadmap status are accurate.
- [ ] Markdown links resolve and no obsolete redirect document was added.
- [ ] UI work covers loading, error, disconnected, and keyboard-accessible states.
