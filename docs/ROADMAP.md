# Argus Roadmap

## Phase 0 — Product contracts and developer foundation

- Rewrite product, architecture, API, UX, security, contribution, and roadmap documentation.
- Add repository Codex guidance and the Argus development skill.
- Define Pydantic-authoritative event models and generated frontend types.

**Exit:** documentation reflects reality and [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md) contains no unresolved MVP design decisions.

## Phase 1 — Interactive contract prototype

- Implement typed simulated event playback.
- Complete all shared-room, approval, diff, lifecycle, error, and reconnect UI states.
- Validate accessibility and keyboard behavior.

**Exit:** every protocol event renders correctly without a live provider or backend.

## Phase 2 — First real vertical slice

- Create a project-backed session and start a worktree.
- Run Coordinator, Planner, and Builder through the shared event log.
- Support human messages, mentions, pause/cancel, approval, and diff review.

**Exit:** a user can complete one isolated, provider-backed coding task end to end.

## Phase 3 — Extensible team

- Add Reviewer, Tester, UI Agent, custom roles, and local skill packages.
- Add capability routing, handoffs, budgets, and loop limits.

**Exit:** a user can configure a custom role and skill without changing source code.

## Phase 4 — Reliability and provider breadth

- Add native provider adapters, persistence, replay, recovery, keychain storage, and bounded parallel sessions.

**Exit:** sessions survive reconnect/restart and providers present a normalized experience.

## Phase 5 — Release readiness

- Package the sidecar, tighten Tauri permissions, add CI, security checks, cross-platform smoke tests, and release artifacts.

**Exit:** supported-platform installation and end-to-end workflows are repeatable in CI.
