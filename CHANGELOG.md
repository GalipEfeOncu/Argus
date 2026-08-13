# Changelog

All notable user-visible changes to Argus are recorded here. The project follows
[Semantic Versioning](https://semver.org/) and the release policy in
[docs/IMPLEMENTATION_SPEC.md](docs/IMPLEMENTATION_SPEC.md#14-versioning-and-release-train).

## Unreleased

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

No stable Argus version has been published yet. The manifest version `0.1.0` is
the current development baseline, not a stable release claim.
