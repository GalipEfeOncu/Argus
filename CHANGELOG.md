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

No stable Argus version has been published yet. The manifest version `0.1.0` is
the current development baseline, not a stable release claim.
