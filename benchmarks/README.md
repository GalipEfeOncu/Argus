# Release benchmark evidence

This directory contains the versioned benchmark-result schema and deterministic
fixture manifest. It deliberately contains no measured baseline: Phase 0 still
needs native, packaged release measurements on each supported target.

Complete release results must contain every metric required for that target OS
with its prescribed unit and a measured value; Linux AppImage, Windows installer,
and macOS installer metrics are mutually platform-specific. They also require
measured compressed and uncompressed attribution for frontend chunks, Rust shell,
Python runtime/dependencies, provider adapters, and platform resources. Result
metadata identifies the OS, architecture, app and sidecar versions, fixture
dataset, hardware class, release provenance, and disabled telemetry. Comparisons
reject different OS, architecture, hardware class, or dataset values.
Debug and Vite/dev-server provenance are rejected before comparison. An
`unsupported` result records an unavailable runner without being usable as a
baseline.

Useful commands:

```bash
npm run benchmark:fixtures -- --output-dir /tmp/argus-bench-fixtures
npm run benchmark:validate -- --input result.json
npm run benchmark:compare -- --baseline baseline.json --actual result.json
npm run benchmark:report -- --baseline baseline.json --actual result.json
npm run benchmark:attribution -- --input artifacts.json
npm run benchmark:release
```

`benchmark:release` currently returns an explicit unsupported result because
this repository does not yet have a native packaged Tauri/sidecar benchmark
runner. It never creates a baseline from the current development host.

Artifact attribution reads the real files listed in an input array; the emitted
record retains only the supplied logical ID and file name, never the local path:

```json
[
  {
    "id": "initial-web-chunk",
    "category": "frontend-chunk",
    "path": "dist/assets/index-<hash>.js"
  }
]
```
