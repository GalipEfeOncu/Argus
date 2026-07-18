# Benchmark fixtures

`manifest.json` is the source of truth for deterministic benchmark fixture
dimensions and scenarios: empty launch, 100/10,000-event sessions, 5 MB and
50 MB on-demand diffs, parallel read-only agents, one mutating agent, sidecar
idle/restart, and reconnect/replay. The fixture payloads are generated outside
the repository so the 5 MB and 50 MB diffs are never committed as opaque binary
blobs.

Generate the standard fixtures:

```bash
npm run benchmark:fixtures -- --output-dir /tmp/argus-bench-fixtures
```

Add the intentionally on-demand 50 MB diff only when a release benchmark needs
it:

```bash
npm run benchmark:fixtures -- --output-dir /tmp/argus-bench-fixtures --include-on-demand
```

The generator writes no credentials, project content, or host paths into fixture
payloads.
