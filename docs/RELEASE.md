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

## Protected release environment

Create a GitHub environment named `release` with required reviewer approval and
restrict it to protected immutable tags. Add a repository ruleset that blocks
tag updates/deletions for `v*`. Store only these release credentials:

- `WINDOWS_CERTIFICATE`: base64 PKCS#12 code-signing certificate;
- `WINDOWS_CERTIFICATE_PASSWORD`;
- `APPLE_CERTIFICATE`: base64 Developer ID Application certificate;
- `APPLE_CERTIFICATE_PASSWORD`;
- `APPLE_SIGNING_IDENTITY`;
- `APPLE_API_ISSUER`, `APPLE_API_KEY`, and base64 `APPLE_API_KEY_BASE64` for the
  App Store Connect notarization key.

Normal CI has read-only repository permission and cannot access this
environment. Release jobs fail when a required target credential is absent.

## Release transaction

After every applicable row in [PUBLISH_CHECKLIST.md](PUBLISH_CHECKLIST.md) has a
durable evidence reference, follow
[Implementation Specification section 14](IMPLEMENTATION_SPEC.md#14-versioning-and-release-train):

1. choose the SemVer, move `Unreleased` changelog entries, run
   `npm run version:set -- <version>`, verify, merge, and create the annotated
   immutable tag `v<version>` on that exact commit;
2. dispatch **Publish immutable release** from that exact tag ref (for example,
   `gh workflow run release.yml --ref v<version>`) with the same tag input, the
   durable checklist evidence reference, and the correct prerelease flag;
3. approve the protected `release` environment only after comparing the tag,
   source commit, and evidence; and
4. independently verify the published `SHA256SUMS`, SBOM, installer signatures,
   notarization result, and versioned generated release notes.

The workflow refuses a lightweight tag or tag/version mismatch, re-runs supply
chain evidence at the tag, builds every package natively, signs Windows and
macOS artifacts, notarizes macOS packages, records checksums/evidence, and then
creates the GitHub release. It never creates or moves the source tag.

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
