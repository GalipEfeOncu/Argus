# Threat model

## Scope and assets

This model covers the Argus desktop shell, local FastAPI sidecar, SQLite state,
session workspaces, provider adapters, local skill packages, CI, and release
artifacts. The primary assets are provider credentials, project contents,
approval and grant state, ordered collaboration evidence, accepted changes, and
the integrity of installed Argus binaries.

Argus assumes the installed desktop application, operating-system user account,
native credential store, and configured model provider are trusted within their
documented roles. Signed releases bind that application to a verified publisher.
An unsigned community Alpha does not; its user must download from the official
repository and match `SHA256SUMS` before installation, while recognizing that a
co-hosted checksum cannot authenticate the publisher or protect against a
compromised repository. Model responses, imported skills, project files, tool
arguments, web content, and dependency metadata are untrusted.

## Trust boundaries and mitigations

| Boundary or threat | Required mitigation |
| --- | --- |
| Model output requests an unsafe tool or invents authority | The deterministic backend validates capability, exact workspace scope, approval, budget, lease, and cancellation state. Prompt text is never authorization. |
| A path, symlink, reparse point, patch, or shell argument escapes the session workspace | Canonical path checks, bounded reads, non-regular-file rejection, isolated worktrees/snapshots, and permission-aware tools fail closed. |
| A local web page or process reaches the sidecar | The sidecar binds an ephemeral loopback port, requires a process-local bearer token, validates origins, and keeps the stronger credential bridge native-only. |
| Credentials or private reasoning leak through persistence or support data | Secrets stay in the OS credential store; events, logs, SQLite, exports, and support bundles exclude credential material, raw private reasoning, and project contents. |
| A crash or reconnect repeats a mutating operation | Durable idempotency receipts, leases, checkpoints, ordered events, and `outcome_unknown` reconciliation prevent automatic mutation replay. |
| A migration corrupts durable configuration or session data | Startup verifies the existing SQLite database and creates a checksummed consistent backup before any pending migration; recovery is explicit and retains the displaced database. |
| A dependency, CI action, or release artifact is replaced or compromised | Application dependencies use committed lockfiles, CI actions and tool versions are pinned, secret/vulnerability/license audits run, an SBOM is generated, release tags are immutable, and published artifacts carry SHA-256 checksums. Signed modes additionally provide platform publisher identity; unsigned Alpha users must verify checksums manually. |
| A release credential is exposed to ordinary CI | Signing secrets are available only to the protected `release` environment and the manual immutable-tag workflow; normal pull-request and main-branch jobs have read-only repository permissions. |

## Abuse cases

- A malicious repository can contain prompt injection, huge files, unusual
  encodings, executable hooks, symlinks, or filenames that resemble options.
  Workspace tools treat these as data, enforce size/time bounds, and never infer
  permission from repository text.
- A malicious provider or skill can request secrets, broader paths, network
  access, or destructive commands. Non-bypassable denials and explicit grants
  still apply, and imported skills remain disabled until reviewed.
- A compromised dependency can execute during build or runtime. Lockfiles,
  minimal packaging, audits, SBOM evidence, native target builds, and checksummed
  releases reduce this risk; signed modes additionally authenticate the
  publisher, but neither control can prove a dependency benign.

## Residual risks and exclusions

An administrator, debugger, malware, or other process already controlling the
same OS account may read application memory or project files; Argus is not a
sandbox against a compromised host. A selected model provider receives the
context deliberately sent to it and remains subject to that provider's privacy
and retention terms. Local SQLite metadata is protected by OS account and disk
controls rather than application-level encryption. An unsigned community Alpha
lacks authenticated publisher identity and is unsuitable for unattended or
managed production deployment; checksum verification does not remove that
residual risk. Clean-client security,
certificate trust where applicable, unsigned-warning behavior, keychain
variants, and installer behavior are verified for each publication through
[PUBLISH_CHECKLIST.md](PUBLISH_CHECKLIST.md).

Report newly discovered threats through the private process in
[the repository security policy](../SECURITY.md).
