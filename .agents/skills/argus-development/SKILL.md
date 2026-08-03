---
name: argus-development
description: Implement and verify contract-first changes in the Argus desktop multi-agent workspace. Use for React UI slices, FastAPI runtime/API work, Tauri integration, event-contract changes, agent/skill behavior, security-sensitive tool changes, and documentation updates in this repository.
---

# Argus Development

Implement a focused Argus feature slice while preserving the shared-room, local-first, and user-control invariants.

## Workflow

1. Read `AGENTS.md`, the closest directory-specific `AGENTS.md`, and use
   `docs/README.md` to select the relevant source-of-truth documents.
2. Classify the change as internal-only, user-visible, roadmap completion/phase
   exit, or release preparation. Apply the changelog, completion-evidence,
   release-readiness, publication-checklist, milestone, and version companions
   required by `AGENTS.md`.
3. Inspect existing code and state the affected contract, persistence, UI, and permission boundaries.
4. For protocol work, update the backend model first; then generated types, frontend reducer/simulator, tests, and `docs/API.md`.
5. Keep changes small enough to validate end-to-end. Do not replace a working layer with an unverified broad rewrite.
6. Run `scripts/verify.sh` with the narrowest appropriate scope (`docs`,
   `frontend`, `backend`, or `tauri`), then use `all` before handoff when all
   toolchains are available.
7. Review `git diff` for secrets, generated/version drift, unrelated edits, and inaccurate documentation.
8. At handoff, report the classification, companion updates, version decision,
   verification evidence, and checks not run.

## Guardrails

- Treat model output and tool arguments as untrusted.
- Preserve event ordering, command idempotency, and user intervention during streaming.
- Keep credentials out of client persistence, database payloads, logs, fixtures, and exports.
- Preserve worktree isolation and policy enforcement in the backend, never only in prompts.
- Show user-visible action summaries, not private chain-of-thought.
- Do not bump the application version outside a dedicated release change.
- Do not mark a roadmap slice or phase complete without its required evidence.

## References

- Read `references/contract-checklist.md` for REST/WebSocket changes.
- Read `docs/UX_SPEC.md` for UI work and `docs/SECURITY.md` for tools, credentials, or workspace changes.
- Read `docs/ROADMAP.md` for slice completion or phase exits; read
  `docs/PUBLISH_CHECKLIST.md`, `docs/IMPLEMENTATION_SPEC.md` section 14, and
  `CHANGELOG.md` for releases.
- Treat `docs/README.md` as the documentation ownership and reading map.
