# Argus

> A transparent, local-first multi-agent workspace for software projects.

Argus lets you run the models you choose against a local project while keeping the collaboration visible. Agents, a Coordinator, and the user work in one shared timeline: you can see assignments, messages, tool activity, diffs, approvals, costs, and handoffs as they happen.

Argus is not a black-box coding assistant. It is a controllable orchestration workspace.

## Status

Argus is in active pre-alpha development. The repository currently contains the Tauri, React, FastAPI, and LangGraph foundations plus an initial UI. The shared-room orchestration runtime described below is the active implementation target; see the [roadmap](docs/ROADMAP.md) for milestone criteria.

## Product principles

- **Transparent by default.** Show messages, concise decision summaries, tool activity, diffs, approvals, usage, and failures. Do not present private model reasoning as a product feature.
- **Local-first.** Sessions operate on projects selected by the user. Provider credentials belong in the operating-system credential store, never in source control or browser storage.
- **User-controlled.** Pause, redirect, mention, approve, reject, or stop participants at any time.
- **Safe defaults, configurable freedom.** Work in an isolated worktree by default; let experienced users choose stricter or more autonomous policies explicitly.
- **Extensible teams.** Start with built-in roles and skill bundles, then customize or add roles for a project.

## Target workflow

1. Choose a local project and configure a session policy.
2. Select a model for each built-in or custom agent.
3. Start a shared room where the visible Coordinator assigns and hands off work.
4. Follow the live timeline, intervene with messages or mentions, and review requested tool permissions.
5. Inspect generated diffs and accept the isolated worktree changes when ready.

## Planned MVP

| Area | MVP capability |
| --- | --- |
| Participants | Coordinator, Planner, Builder, Reviewer, Tester, UI Agent, and custom capability-based roles |
| Providers | Native OpenAI, Anthropic, Google, plus an OpenAI-compatible adapter for OpenRouter and local servers |
| Collaboration | Ordered shared timeline, mentions, assignments, handoffs, pause/resume/cancel, and reconnect/replay |
| Safety | Worktree isolation, policy profiles, scoped approvals, diffs, and project-level writer locks |
| Skills | Built-in bundles plus validated local skill-package import |
| Desktop | Tauri v2 application for Linux, macOS, and Windows |

## Development

### Prerequisites

- Node.js 18+
- Rust stable
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

### Setup

```bash
npm install
(cd backend && uv sync)
npm run tauri:dev
```

Run the backend separately during backend development:

```bash
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Verification

```bash
npm run type-check
(cd backend && .venv/bin/python3 -c "import app.main; print('backend import OK')")
(cd src-tauri && cargo check)
```

## Documentation

- [Product definition](docs/PRODUCT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [UX specification](docs/UX_SPEC.md)
- [API and event protocol](docs/API.md)
- [Security model](docs/SECURITY.md)
- [Implementation specification](docs/IMPLEMENTATION_SPEC.md)
- [Roadmap](docs/ROADMAP.md)
- [Contributing](CONTRIBUTING.md)

## License

MIT © Galip Efe Oncu
