# Documentation Guidance

These rules extend the root `AGENTS.md` for every file under `docs/`.

## Authority and scope

- Keep the source-of-truth ownership table in `README.md` accurate.
- Update an authoritative document instead of adding a second document for the same decision.
- Use `ROADMAP.md` for future sequencing and exit criteria, not as evidence that a feature exists.
- Keep implementation detail in `IMPLEMENTATION_SPEC.md`; keep product outcomes in `PRODUCT.md`.
- Keep protocol shapes in `API.md`, visible behavior in `UX_SPEC.md`, and enforcement boundaries in `SECURITY.md`.

## Writing for agents and humans

- Put constraints, ownership, acceptance criteria, and verification commands in explicit sections.
- Distinguish `current`, `target`, and `planned` behavior wherever ambiguity is possible.
- Prefer links over duplicated rules so agent context does not contain conflicting instructions.
- Keep examples free of secrets, real user paths, and provider credentials.
- After moving or renaming a file, update all repository links and the documentation index.

## Verification

Run `.agents/skills/argus-development/scripts/verify.sh docs` and inspect the
rendered Markdown when changing tables, nested lists, or diagrams.
