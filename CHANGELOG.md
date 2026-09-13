# Changelog

All notable user-visible changes to Argus are recorded here. The project follows
[Semantic Versioning](https://semver.org/) and the release policy in
[docs/IMPLEMENTATION_SPEC.md](docs/IMPLEMENTATION_SPEC.md#14-versioning-and-release-train).

## Unreleased

### Added

- Provider Settings now includes presets for OpenAI, Anthropic, Google Gemini,
  OpenRouter, DeepSeek, Moonshot/Kimi, xAI, Mistral AI, Groq, and local Ollama.
  Each configured provider discovers its bounded model catalogue, supports
  search and direct model selection, and keeps non-chat models visible but
  unavailable for direct chat.
- Argus now uses its new brand mark in the workspace shell, browser icon, and
  desktop application icon set, alongside a refined responsive control-room UI.
- Configured Coordinators can now delegate read-only workspace inspection to a
  configured specialist, with bounded audited tools and a follow-up Coordinator
  turn that reports the verified result; mutating specialist work remains denied.
- Starting a session now runs its explicitly configured Coordinator provider in
  a durable background lifecycle, with visible final or failure outcomes,
  reconnectable events, safe pause/cancel fencing, and no provider fallback.
- The primary New action now opens a direct chat immediately when a provider is
  configured, remembers the selected non-secret model reference, and keeps a
  draft available with a clear Provider Settings path when no API credential is
  ready.
- An optional offline profile now lets the device owner set a local display name
  and bio, with accessible edit, loading, retry, and save states and no online
  account or browser-persisted identity.

### Fixed

- Provider credentials now use the operating-system keyring on Linux and wake
  an idle native sidecar before handing a key to the local runtime.
- Provider catalogues now exclude extraction, embedding, transcription, and
  other non-chat models from direct-chat selection while keeping them visible
  in Settings; zero-cost discovered models are preferred for automatic chat
  startup.
- Restored direct chats now renew their short-lived native provider lease when
  the session view opens after an Argus restart.
- Direct-chat provider failures now explain whether the API key, account
  credits, selected model, request, or temporary provider availability needs
  attention instead of showing one generic error.
- Provider Settings now explains when API-key providers are being configured
  outside the Tauri desktop credential-store boundary instead of reporting a
  generic save failure.
- Workspace pages now share the direct-chat visual language: quieter surfaces,
  lighter separators, restrained status treatments, and less decorative empty
  states across the dashboard, settings, profile, setup, and session views.
- The direct-chat entry screen now keeps the composer as its single panel,
  blends the welcome copy into the page background, and reduces provider setup
  to a compact inline prompt.
- The empty Dashboard now presents one clear primary start action, uses a
  semantic sessions heading, labels catalogue recovery controls for assistive
  technology, and keeps runtime status readable at narrow window widths.
- Session entry now uses consistent session terminology, removes ambiguous
  decorative symbols, and makes each choice describe its actual destination.
- Direct chats now use projectless durable sessions with the shared ordered
  timeline, while project sessions retain their existing isolated workspace and
  specialist setup flow.
- Typography now uses local operating-system font stacks, avoiding an external
  font request and preserving the desktop interface when offline.
- Session setup and runtime copy now match the production read-only worker:
  Coordinator can route one specialist inspection per turn, unsupported write,
  test, gate, direct-write, and pre-authorization controls are no longer offered,
  and submitted authority is narrowed before session creation.
- Packaged desktop sidecars now include the provider adapters exposed by the
  application and verify them offline during the frozen build, instead of
  failing only after a configured provider session starts.
- The workspace shell and session context now remain usable at narrow window
  sizes, expose truthful runtime status and keyboard navigation, and provide
  retryable provider, model, project, and session catalogue failure states.
- Composer drafts now remain editable during session reconnects and are cleared
  only after the correlated room event confirms delivery. Users can also send
  Coordinator guidance while a separate approval remains pending.
- Session setup now requires explicit models from configured provider profiles,
  the runtime rejects placeholder or unknown provider bindings before creating
  a workspace, and the live WebSocket bundle no longer includes simulator paths.
- Removed the obsolete placeholder model endpoint and stale built-in model,
  approval-ID, settings, and frontend version fallbacks.
- Starting or approving a session no longer launches the deterministic demo
  task or writes its fixed reference file in a real project workspace.
- The navigation shell now loads durable local projects and sessions instead of
  showing sample projects, a fake account, or controls with no available action.

## [1.0.0-alpha.2] - 2026-08-16

### Added

- Coordinator-first shared-room contracts, durable scheduling, isolated
  workspaces, required-role gates, and configurable budget counters for the
  in-progress 1.0 product.
- Durable loop detection and bounded limit resolution: repeated review findings,
  failures, and unchanged workspaces now request a user decision, a single
  tool-free Coordinator choice, or stop according to the session policy.
- Durable approval and grant enforcement: permission profiles, capability
  overrides, expiring exact-scope grants, and no-interruption denial now remain
  enforced across reconnects and restarts.
- Versioned built-in agent templates, immutable custom/override role definitions,
  capability/evidence-based routing, and session-safe definition snapshots.
- Local skill-package import, trust review, explicit enablement, immutable
  content snapshots, and tool/permission escalation checks.
- Native provider profiles for OpenAI, Anthropic, Google, and OpenAI-compatible
  services, including model discovery, manual model IDs, normalized streaming
  behavior, and OS credential-store references instead of browser-stored keys.
- Restart-safe session recovery: durable projections, grants, counters, worker
  checkpoints, leases, and unknown tool/provider outcomes are reconciled after
  a sidecar restart without automatically replaying a mutating operation.
- Review and acceptance workflow for isolated results: users can inspect file
  changes, evidence, gates, limits, usage, and Coordinator summaries; safely
  apply policy-checked changes, reject, export a patch, or start a fresh
  follow-up session. Original-project drift blocks automatic writes.
- Local runtime diagnostics and an explicit redacted support-bundle export,
  including queue/lease status, provider latency, event lag, usage, and safe
  degraded-mode guidance without project content or credentials.
- Hardened desktop lifecycle with a version-matched frozen sidecar, dynamic
  authenticated localhost transport, origin checks, bounded crash restart,
  graceful shutdown fallback, single-instance coordination, least-privilege
  Tauri capabilities, and reproducible binary-size attribution.
- Native Windows, macOS Intel/Apple Silicon, and Ubuntu packaging quality
  automation; current Ubuntu/Debian compatibility probes; embedded WebView2
  bootstrap; and improved keyboard, contrast, screen-reader, reduced-motion,
  Unicode/long-path, symlink, line-ending, and process-cancellation coverage.
  Workspace search now has a bounded literal fallback when ripgrep is absent.
- Supply-chain and protected release automation with immutable dependency/tool
  pins, SBOM and license evidence, vulnerability/secret audits, reproducible
  frontend builds, native signing/notarization, checksums, and versioned notes.
  Existing databases now receive a verified pre-migration backup with an
  explicit checksum-checked recovery path; threat, privacy, operations, known
  limits, and private vulnerability-reporting guidance are published.

### Changed

- Release governance now supports a documented solo-maintainer approval mode
  while preserving separate credential and publication gates. Releases use
  independent review whenever another maintainer is available.
- Release automation now supports a zero-cost, prominently labelled unsigned
  community Alpha mode while preserving immutable tags, native builds, SBOM,
  checksums, clean-client evidence, and separate publication approval. Beta,
  release-candidate, and stable publication still require platform signing.

### Fixed

- Windows native packaging now converts PyInstaller migration inputs to native
  paths, avoiding Git Bash drive-path corruption.
- Version preparation now regenerates and validates the OpenAPI contract so its
  release metadata cannot drift from synchronized application manifests.
- Release automation now stages checksummed artifacts behind a separate
  publication approval so clean-client and reference-hardware evidence can be
  completed before a GitHub Release is created.
- Sidecar shutdown now owns, drains, and awaits in-flight vertical worker tasks;
  cancellation also closes SQLite connections before the event loop exits.
- CI artifact and secret-scan actions now use immutable Node 24 releases instead
  of deprecated Node 20 action runtimes.

## [1.0.0-alpha.1] - 2026-08-16

Not published. The Windows native sidecar build failed before artifact staging;
the immutable tag is retained as failed-candidate evidence in issue #5.

No stable Argus version has been published yet. Version `1.0.0-alpha.1` is an
unpublished failed candidate. Version `1.0.0-alpha.2` is an unsigned community
prerelease and not a stable release claim.
