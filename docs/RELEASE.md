# Release automation operator guide

## Continuous supply-chain evidence

`.github/workflows/supply-chain.yml` installs application dependencies from the
committed npm, uv, and Cargo lockfiles. It generates a deterministic CycloneDX
SBOM and license inventory, rejects forbidden strong-copyleft dependency
licenses or unresolved metadata, runs npm, Python, and Rust vulnerability audits, and compares two
independent clean frontend builds byte-for-byte. Standard CI separately scans
the full Git history for secrets, and the supply-chain workflow repeats that
scan at a release tag. Audit reports are retained with the SBOM. GitHub Actions use immutable commit SHAs;
Node, Python, Rust, uv, pip-audit, and cargo-audit versions are explicit.

Dependabot proposes weekly lockfile/action updates. Updating a pin requires the
same audit and verification as any other dependency change. A scanner outage or
unavailable advisory database is a failed check, not a pass.
Target-specific packages that are absent from the audit runner use exact-version
metadata overrides in `supply-chain-license-policy.json`; a version change
invalidates the override and requires a new source-backed review.

## Protected release environments

Create GitHub environments named `release` and `release-publication`, both with
required reviewer approval, administrator bypass disabled, and deployment
restricted to protected immutable `v*` tags. The `release` environment owns
signing/notarization credentials; the separate `release-publication`
environment is the final deliberate gate after the staged artifacts pass
clean-client, accessibility, and reference-performance checks. Add a repository
ruleset that blocks tag updates/deletions for `v*`.

Use one of these governance modes and record it in the durable release summary:

- **Team mode (preferred when another maintainer is available):** configure an
  independent required reviewer for both environments and enable GitHub's
  prevent-self-review protection.
- **Solo-maintainer mode:** the initiating maintainer may be the sole required
  reviewer for both environments and prevent-self-review may be disabled. The
  durable evidence must record `governanceMode: solo-maintainer`, the approving
  account, and why no independent reviewer was available. This exception does
  not combine the environments, remove either manual approval, allow
  administrator bypass, or permit approval before its corresponding evidence is
  complete. Return to team mode when another maintainer is available.

## Signing modes

The release workflow supports two explicit modes:

- `unsigned-community-alpha` is the zero-cost community distribution path. It
  is allowed only for an `-alpha.N` version published as a GitHub prerelease.
  Windows and macOS artifacts are neither code-signed nor notarized. The
  workflow records the mode in `release-evidence.json`, adds
  `UNSIGNED-RELEASE.txt` to the checksummed artifact set, and places a prominent
  warning in the GitHub Release notes. The immutable tag, native builds, SBOM,
  checksums, clean-client checks, and both manual environment approvals remain
  mandatory.
- `signed` is required for Beta, release-candidate, and stable publication. It
  signs Windows artifacts and signs/notarizes macOS artifacts using credentials
  held only by the protected `release` environment.

An unsigned community Alpha does not establish operating-system publisher trust.
Users must expect Windows SmartScreen and macOS Gatekeeper warnings and verify
files downloaded from the official Argus repository against the published
`SHA256SUMS`. A co-hosted checksum detects download corruption or an accidental
mismatch; it does not replace a platform signature or protect against compromise
of the repository itself. Do not describe such a build as signed, notarized,
stable, or suitable for unattended/managed rollout.

For `signed` mode, store only these credentials in `release`:

- `WINDOWS_CERTIFICATE`: base64 PKCS#12 code-signing certificate;
- `WINDOWS_CERTIFICATE_PASSWORD`;
- `APPLE_CERTIFICATE`: base64 Developer ID Application certificate;
- `APPLE_CERTIFICATE_PASSWORD`;
- `APPLE_SIGNING_IDENTITY`;
- `APPLE_API_ISSUER`, `APPLE_API_KEY`, and base64 `APPLE_API_KEY_BASE64` for the
  App Store Connect notarization key.

Normal CI has read-only repository permission and cannot access either
environment. Signed release jobs fail when a required target credential is
absent; unsigned community Alpha jobs do not read signing credentials. Do not
store signing credentials in `release-publication`.

## Release transaction

Follow the staged transaction in
[Implementation Specification section 14](IMPLEMENTATION_SPEC.md#14-versioning-and-release-train):

1. complete all source/preflight rows that do not require the final staged
   packages; choose the SemVer, move `Unreleased` changelog entries, run
   `npm run version:set -- <version>`, verify, merge, and create the annotated
   immutable tag `v<version>` on that exact commit;
2. dispatch **Publish immutable release** from that exact tag ref (for example,
   `gh workflow run release.yml --ref v<version>`) with the same tag input, the
   stable durable-checklist evidence reference, the correct prerelease flag, and
   the explicit signing mode. Use `unsigned-community-alpha` only with an
   `-alpha.N` tag and `prerelease: true`;
3. approve `release` only after comparing the tag, source commit, and preflight
   evidence. The workflow builds the native matrix, applies signing/notarization
   only in `signed` mode, checksums everything, and uploads one staged artifact
   set but cannot publish it yet;
4. download that staged set from the workflow run, verify `SHA256SUMS`, and use
   those exact files to complete every remaining clean-client, accessibility,
   lifecycle, backup, and reference-performance row. Update the durable evidence
   at the reference supplied when the workflow was dispatched; and
5. have the configured approver compare the completed evidence, tag, source
   commit, and staged checksums before approving `release-publication`. In team
   mode this approver must be independent; in recorded solo-maintainer mode the
   initiating maintainer may perform this second, separate approval only after
   all pre-publication evidence is complete. After the workflow publishes,
   independently reverify the GitHub Release assets, SBOM, checksums, versioned
   generated notes, and either the expected signatures/notarization or the
   expected unsigned warnings for the selected mode.

The workflow refuses a lightweight tag, tag/version mismatch, or an unsigned
mode used outside a prerelease `-alpha.N` tag. It re-runs supply-chain evidence
at the tag, builds every package natively, and records the selected signing
mode, checksums, and evidence before publication approval. It publishes only
that staged set and never creates or moves the source tag. If a staged candidate
fails a gate, do not approve publication and do not reuse its tag or version;
prepare the correction under a new patch or prerelease number.

Native artifacts are not assumed reproducible across packaging or
signing/notarization systems because timestamps and platform tooling
intentionally add metadata. Their immutable source tag, SBOM, native build logs,
declared signing mode, and checksums provide provenance; signed mode additionally
provides platform signatures and notarization. Unsigned frontend output is
compared reproducibly in CI.

RustSec currently reports maintenance warnings for Tauri's required Linux GTK3
binding chain, including the upstream `glib` iterator advisory. Cargo audit
still fails on vulnerability advisories; warning output is retained for review.
Removing this residual warning depends on Tauri/WebKitGTK moving off that
upstream chain and is tracked as a known platform limit rather than being
silently marked resolved.
