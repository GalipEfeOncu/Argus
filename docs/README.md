# Argus Documentation

This directory contains the product and engineering contracts for Argus. The
documents are intentionally kept at stable paths so contributors and coding
agents can link to one authoritative source instead of duplicating rules in
prompts or implementation notes.

## Source-of-truth map

| Question | Authoritative document | Status |
| --- | --- | --- |
| What are we building and for whom? | [PRODUCT.md](PRODUCT.md) | Product contract |
| Which layer owns a responsibility? | [ARCHITECTURE.md](ARCHITECTURE.md) | Target architecture |
| What crosses REST or WebSocket? | [API.md](API.md) | Target protocol; transitional endpoints are labeled |
| What must the user see and control? | [UX_SPEC.md](UX_SPEC.md) | UX contract |
| What is allowed and where is it enforced? | [SECURITY.md](SECURITY.md) | Security contract |
| Which MVP decisions are already settled? | [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md) | Implementation contract |
| What performance and platform budgets must pass? | [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md#12-performance-and-footprint-budgets) | Release contract |
| What should be built next? | [ROADMAP.md](ROADMAP.md) | Phase plan and exit criteria |

The [design reference](assets/argus-design-reference.png) is visual input, not an
implementation contract. When it conflicts with UX, accessibility, or security
requirements, the written contracts win.

## Reading matrix

Read only the rows relevant to the change, plus `PRODUCT.md` whenever product
behavior or scope may change.

| Change area | Required reading |
| --- | --- |
| React components, state, or interaction | `UX_SPEC.md`, `API.md` when protocol state is involved |
| FastAPI runtime, scheduling, or persistence | `ARCHITECTURE.md`, `IMPLEMENTATION_SPEC.md`, `API.md` |
| REST/WebSocket contract | `API.md`, `IMPLEMENTATION_SPEC.md` section 6 |
| Filesystem, shell, git, credentials, or Tauri permissions | `SECURITY.md`, `ARCHITECTURE.md` |
| Agents, roles, skills, or orchestration | `PRODUCT.md`, `ARCHITECTURE.md`, `IMPLEMENTATION_SPEC.md` |
| Roadmap or status claim | `ROADMAP.md` and the current implementation/tests |

## Documentation rules

- Describe current behavior as current and unimplemented behavior as target or planned.
- Keep one owner for each decision. Link to it instead of copying normative text.
- Update code, tests, generated contracts, and related documentation in the same change.
- Use relative links and repository-relative paths in prose and commands.
- Prefer durable headings; other documents and agent tasks may deep-link to them.
- Do not include credentials, private model reasoning, personal machine paths, or user project data.

Repository-wide agent instructions live in [../AGENTS.md](../AGENTS.md).
Directory-specific documentation instructions live in [AGENTS.md](AGENTS.md).
