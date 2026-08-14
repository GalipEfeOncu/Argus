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
required reviewer approval and restricted to protected immutable tags. The
`release` environment owns signing/notarization credentials; the separate
`release-publication` environment is the final human gate after the staged
artifacts pass clean-client, accessibility, and reference-performance checks.
Add a repository ruleset that blocks tag updates/deletions for `v*`. Store only
these credentials in `release`:

- `WINDOWS_CERTIFICATE`: base64 PKCS#12 code-signing certificate;
- `WINDOWS_CERTIFICATE_PASSWORD`;
- `APPLE_CERTIFICATE`: base64 Developer ID Application certificate;
- `APPLE_CERTIFICATE_PASSWORD`;
- `APPLE_SIGNING_IDENTITY`;
- `APPLE_API_ISSUER`, `APPLE_API_KEY`, and base64 `APPLE_API_KEY_BASE64` for the
  App Store Connect notarization key.

Normal CI has read-only repository permission and cannot access either
environment. Release jobs fail when a required target credential is absent.
Do not store signing credentials in `release-publication`.

## Release transaction

Follow the staged transaction in
[Implementation Specification section 14](IMPLEMENTATION_SPEC.md#14-versioning-and-release-train):

1. complete all source/preflight rows that do not require the final signed
   packages; choose the SemVer, move `Unreleased` changelog entries, run
   `npm run version:set -- <version>`, verify, merge, and create the annotated
   immutable tag `v<version>` on that exact commit;
2. dispatch **Publish immutable release** from that exact tag ref (for example,
   `gh workflow run release.yml --ref v<version>`) with the same tag input, the
   stable durable-checklist evidence reference, and the correct prerelease flag;
3. approve `release` only after comparing the tag, source commit, and preflight
   evidence. The workflow builds, signs, notarizes, checksums, and uploads one
   staged artifact set but cannot publish it yet;
4. download that staged set from the workflow run, verify `SHA256SUMS`, and use
   those exact files to complete every remaining clean-client, accessibility,
   lifecycle, backup, and reference-performance row. Update the durable evidence
   at the reference supplied when the workflow was dispatched; and
5. have an independent reviewer compare the completed evidence, tag, source
   commit, and staged checksums before approving `release-publication`. After the
   workflow publishes, independently verify the GitHub Release assets, SBOM,
   installer signatures, notarization result, and versioned generated notes.

The workflow refuses a lightweight tag or tag/version mismatch, re-runs supply
chain evidence at the tag, builds every package natively, signs Windows and
macOS artifacts, notarizes macOS packages, and records checksums/evidence before
the publication approval. It publishes only that staged set and never creates
or moves the source tag. If a staged candidate fails a gate, do not approve
publication and do not reuse its tag or version; prepare the correction under a
new patch or prerelease number.

Native artifacts are not assumed reproducible across signing/notarization
systems because timestamps and platform tooling intentionally add metadata.
Their immutable source tag, SBOM, native build logs, signatures, and checksums
provide provenance; unsigned frontend output is compared reproducibly in CI.

RustSec currently reports maintenance warnings for Tauri's required Linux GTK3
binding chain, including the upstream `glib` iterator advisory. Cargo audit
still fails on vulnerability advisories; warning output is retained for review.
Removing this residual warning depends on Tauri/WebKitGTK moving off that
upstream chain and is tracked as a known platform limit rather than being
silently marked resolved.
