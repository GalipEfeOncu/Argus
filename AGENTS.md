# Argus Repository Guidance

This is the entry point for coding agents. Read it before planning or editing. More
specific `AGENTS.md` files under `src/`, `backend/`, `src-tauri/`, and `docs/`
extend these rules for their directory trees.

## Start here

1. Read [docs/README.md](docs/README.md) and the documents it marks as required
   for the area being changed.
2. Inspect nearby implementation and tests before proposing a solution. Treat
   documentation marked as `target` as a contract to implement, not proof that
   the behavior already exists.
3. Classify the change as internal-only, user-visible, roadmap completion/phase
   exit, or release preparation and apply the companion-update rules below.
4. State the affected contract, persistence, UI, workspace, and permission
   boundaries. Mark a boundary `not affected` when appropriate.
5. Make one focused vertical slice and keep generated artifacts synchronized
   with their authoritative source.
6. Run the narrowest relevant verification, then review the complete diff for
   unrelated changes, secrets, stale claims, and generated-file drift.

## Product invariants

Argus is a local-first, transparent multi-agent workspace. Preserve these rules in every change:

- The shared timeline is the user-visible source of collaboration truth.
- A visible Coordinator explains assignments and handoffs; deterministic services enforce policy, state, ordering, and tool boundaries.
- Never expose provider credentials or private model reasoning in UI, logs, events, exports, or persistence.
- Worktree isolation and balanced approval policy are the default; more permissive modes require explicit user intent.
- Built-in roles and skills are customizable; custom roles are capability-based.

Use the reading matrix in `docs/README.md`; do not load every specification when
the task affects only one layer.

## Repository boundaries

- `src/` — React 19 client; keep UI state and protocol reducers typed.
- `backend/` — FastAPI runtime; use async I/O and Pydantic at external boundaries.
- `src-tauri/` — native bridge and sidecar lifecycle; use least privilege.
- `docs/` — product and implementation contracts, not aspirational feature claims.
- `.agents/skills/argus-development/` — reusable Codex workflow for this repository.
- `.codex/` — repository-local Codex defaults; do not weaken safety defaults for convenience.

Generated and local-only directories such as `dist/`, `node_modules/`,
`backend/.venv/`, Python caches, and `src-tauri/target/` are not source. Never
edit or commit them as part of a feature.

Do not reintroduce a fixed agent pipeline as product behavior. LangGraph may support a single agent loop but may not own session orchestration state.

## Contract-first changes

For REST or WebSocket behavior:

1. Update the authoritative backend model.
2. Regenerate schema/client types.
3. Update frontend reducers and the event simulator.
4. Add success, reconnect/order, malformed-input, and permission-path tests.
5. Update `docs/API.md`.

Use ordered, versioned events and idempotent client commands. Do not hand-maintain duplicate protocol types.

## Change classification and release hygiene

Apply these companion updates in the same focused change. Link to the owning
contract instead of copying its policy into implementation files.

- **Internal-only:** tests, refactors, build tooling, or documentation with no
  user-visible behavior change do not require an application-version bump.
- **User-visible:** add a concise entry under the appropriate `Unreleased`
  heading in [CHANGELOG.md](CHANGELOG.md). Include safe security fixes without
  publishing exploit details. Do not bump the application version yet.
- **Roadmap completion:** update [docs/ROADMAP.md](docs/ROADMAP.md) only after the
  implementation, tests, generated contracts, and authoritative documentation
  agree. Add the completion-evidence block required by its cross-phase controls;
  never mark target prose as current behavior prematurely.
- **Phase exit:** in addition to completion evidence, run and record the available
  release-readiness runway probes and apply the Alpha/Beta/RC milestone rule.
  Environment- or credential-dependent native checks are recorded as deferred
  publication work; they do not block roadmap completion and are never inferred
  to have passed.
- **Release preparation:** read
  [IMPLEMENTATION_SPEC.md section 14](docs/IMPLEMENTATION_SPEC.md#14-versioning-and-release-train),
  complete [docs/PUBLISH_CHECKLIST.md](docs/PUBLISH_CHECKLIST.md),
  move `Unreleased` changelog entries into the dated release, select SemVer from
  compatibility impact, and run `npm run version:set -- <version>`. Version bumps
  occur only in a dedicated release change, not in ordinary feature work.

At handoff, state the classification, companion files updated, version decision
(`unchanged` for non-release work), and checks or release evidence not run.

## Implementation rules

- Prefer focused vertical slices over broad partial rewrites.
- Do not use `any` in TypeScript; use explicit types or `unknown` with validation.
- Keep React components small and accessible; use design tokens instead of hard-coded colors.
- Keep stores for state, services for I/O/business behavior, and components for rendering.
- Scope every filesystem or shell action to the active session workspace.
- Treat model output as untrusted input.
- Do not store API keys in Zustand persistence, localStorage, SQLite, test fixtures, or logs.

## Agent collaboration

- Split work by independently verifiable boundaries, not by arbitrary file groups.
- Give delegated work a concrete scope, acceptance criteria, relevant source-of-truth documents, and owned paths.
- Keep one writer per file or tightly coupled contract surface. A coordinating agent integrates shared contracts.
- Agents may report concise decisions, evidence, tool results, and blockers; never request or expose private chain-of-thought.
- Do not accept a delegated result without inspecting its diff and running the relevant verification.

## Validation

Preferred entry point:

```bash
.agents/skills/argus-development/scripts/verify.sh docs
.agents/skills/argus-development/scripts/verify.sh frontend
.agents/skills/argus-development/scripts/verify.sh backend
.agents/skills/argus-development/scripts/verify.sh tauri
.agents/skills/argus-development/scripts/verify.sh all
```

The underlying layer checks are:

```bash
npm run type-check
npm run check:version
(cd backend && .venv/bin/python3 -c "import app.main; print('backend import OK')")
(cd src-tauri && cargo check)
```

Do not claim a feature is complete unless implementation, tests, generated
contracts, and documentation agree. Report checks that were not run and why.
