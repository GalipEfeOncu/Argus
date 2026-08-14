# Pre-publish verification

This checklist contains environment- and credential-dependent validation that
cannot be completed reliably during ordinary roadmap development. Roadmap phase
completion proves that the implementation, automated tests, native build matrix,
and documentation agree. It does not authorize publishing an artifact.

Run this checklist for every Alpha, Beta, release-candidate, and stable desktop
publication. A missing result blocks that publication for the affected target;
it does not reopen an already completed roadmap phase. Record the application
version, source commit, artifact checksum, operating-system version, hardware
class, result, and evidence location for every row. Never infer one platform's
result from another platform or from cross-compilation. The durable release
summary must also record the release-governance mode, approving account,
whether GitHub's prevent-self-review protection was enabled, and the selected
signing mode. Solo-maintainer self-approval and unsigned community Alpha
publication are permitted only under their bounded exceptions in
[RELEASE.md](RELEASE.md).

Rows that inspect source or automation are preflight gates. Rows that require a
native package run against the exact checksummed artifact set staged by
`release.yml` from the immutable tag. Keep the workflow paused at its protected
`release-publication` environment while those rows are completed. Publication
approval is forbidden until the durable evidence reference supplied to the
workflow contains every applicable pre-publication result. The final
independent checks of the published assets close the transaction immediately
after publication. See [RELEASE.md](RELEASE.md) for the operator sequence.

## Native distribution

- [ ] Build every artifact from the immutable release tag on its native target
  and confirm the workflow has staged, but not published, the checksummed set.
- [ ] On clean Windows 10 22H2 and Windows 11 x86_64 clients, verify installation
  with and without WebView2 already installed. In `signed` mode, verify the
  installer and executable signature and publisher identity. In
  `unsigned-community-alpha` mode, verify that the absent signature and expected
  SmartScreen warning are accurately disclosed in both staged and published
  warnings; never instruct users to ignore a mismatched checksum.
- [ ] On clean macOS 12+ Apple Silicon and Intel clients, verify the app and DMG.
  In `signed` mode, verify the Developer ID signature, notarization, and
  Gatekeeper result. In `unsigned-community-alpha` mode, verify the expected
  Gatekeeper warning and the documented user-controlled open flow after checksum
  verification; never claim notarization.
- [ ] Verify the AppImage and Debian package on clean Ubuntu 22.04, current
  Ubuntu, and Debian stable x86_64 clients.
- [ ] Verify first launch, update, downgrade rejection, uninstall, and documented
  preservation/removal of configuration and credentials on every supported OS.
- [ ] After publication, independently verify SHA-256 checksums, versioned
  release notes, SBOM, artifact/version metadata, and the declared signing mode
  before announcing the release or closing the transaction.

## Native behavior and accessibility

- [ ] Exercise the supported credential stores and representative keychain
  variants without exposing secrets in logs, events, exports, or crash reports.
- [ ] Verify sleep/resume, forced close, restart/reconnect, sidecar cleanup,
  update, and uninstall leave no orphaned process or duplicate mutation.
- [ ] On every supported client, import a local skill package and reject
  symlink/reparse-point and non-regular-file escapes; verify runtime disk-health
  diagnostics use the native filesystem API; apply added, changed, and deleted
  files while preserving the platform's declared line-ending policy.
- [ ] Create and restore a pre-migration backup on every supported client;
  verify checksums, stale SQLite journal handling, and that the backup directory
  is accessible only to the current OS user (including inherited Windows ACLs).
- [ ] Run keyboard-only and screen-reader smoke tests using Narrator on Windows,
  VoiceOver on macOS, and the supported Linux accessibility stack.
- [ ] Verify native zoom, reduced motion, focus recovery, contrast, and the
  10,000-event timeline on clean supported clients.
- [ ] Run the clean-machine user journey: install, configure a provider, select
  a project, complete a Coordinator task with a restricted pool and bounded
  preauthorization, recover after forced restart, inspect the audit trail, and
  safely apply or export the diff.

## Reference performance

- [ ] Run every fixture from
  [Implementation Specification section 12](IMPLEMENTATION_SPEC.md#12-performance-and-footprint-budgets)
  against each release artifact on its declared reference hardware.
- [ ] Record cold/warm first-window and sidecar readiness, shell/webview/sidecar
  RSS, idle CPU, installer size, long tasks, and 10,000-event interaction.
- [ ] Confirm every hard budget passes. The first stable release has no waiver
  path for a failed hard budget.

## Release transaction

- [ ] Confirm the source tag's **Supply chain** run passed with locked npm/uv/Cargo
  installs, SBOM, license inventory, vulnerability audits, secret scanning, and
  reproducible frontend-build comparison.
- [ ] Verify the protected `release` environment approved the native build,
  the separate `release-publication` environment still awaits the required
  approval for the recorded governance mode, and the workflow's checklist
  evidence points to this exact tag and staged checksums. In solo-maintainer
  mode, do not self-approve publication until every applicable pre-publication
  result has been recorded.
- [ ] Run all repository verification scopes, generated-contract/version drift,
  security scanning, provider conformance, fake-provider end-to-end, recovery,
  workspace-escape, approval-bypass, loop-limit, required-gate, migration, and
  rollback tests.
- [ ] Confirm no credential, private model reasoning, or unintended project data
  appears in persistence, UI, logs, events, fixtures, support bundles, or
  published artifacts.
- [ ] Complete the version, changelog, immutable tag, build, selected signing
  mode, checksum, and release-note transaction in
  [Implementation Specification section 14](IMPLEMENTATION_SPEC.md#14-versioning-and-release-train).
- [ ] Retain a durable release summary. Expiring CI artifacts alone are not
  sufficient evidence.
