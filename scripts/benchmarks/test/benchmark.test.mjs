import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import test from 'node:test';
import { REQUIRED_METRICS, attributeArtifacts, evaluateComparison, nodePlatformToBenchmarkOs, renderComparisonReport, requiredMetricIdsForPlatform, validateBenchmarkResult } from '../core.mjs';

const execute = promisify(execFile);
const root = join(import.meta.dirname, '..', '..', '..');
const fixtureGenerator = join(root, 'scripts/benchmarks/generate-fixtures.mjs');
const benchmarkCli = join(root, 'scripts/benchmarks/benchmark.mjs');

function completeMeasurements(platform, overrides = {}) {
  return requiredMetricIdsForPlatform(platform).map((id) => ({ id, status: 'measured', value: overrides[id]?.value ?? 0, unit: overrides[id]?.unit ?? REQUIRED_METRICS[id].unit }));
}

function result(overrides = {}, provenance = { build: 'release-equivalent', artifactSha256: 'a'.repeat(64), telemetry: 'disabled' }, metadata = {}) {
  const resultMetadata = { os: 'linux', arch: 'x86_64', appVersion: '0.1.0', sidecarVersion: '0.1.0', dataset: 'session-100', hardwareClass: 'reference', ...metadata };
  return {
    schemaVersion: 1,
    status: 'complete',
    metadata: resultMetadata,
    provenance,
    measurements: completeMeasurements(resultMetadata.os, overrides),
    attribution: ['frontendChunk', 'rustShell', 'pythonRuntime', 'pythonDependency', 'providerAdapter', 'platformResource'].map((category) => ({ id: `${category}-fixture`, fileName: `${category}.bin`, category, status: 'measured', compressedBytes: 0, uncompressedBytes: 0 })),
  };
}

test('fixture generation is deterministic and preserves declared dimensions', async () => {
  const first = await mkdtemp(join(tmpdir(), 'argus-bench-one-'));
  const second = await mkdtemp(join(tmpdir(), 'argus-bench-two-'));
  try {
    await Promise.all([execute(process.execPath, [fixtureGenerator, '--output-dir', first, '--include-on-demand']), execute(process.execPath, [fixtureGenerator, '--output-dir', second, '--include-on-demand'])]);
    for (const name of ['empty-launch.scenario.json', 'session-100.json', 'session-10000.json', 'diff-5mb.diff', 'diff-50mb-on-demand.diff', 'parallel-readonly-agents.scenario.json', 'one-mutating-agent.scenario.json', 'sidecar-idle-restart.scenario.json', 'reconnect-replay.scenario.json']) assert.deepEqual(await readFile(join(first, name)), await readFile(join(second, name)), name);
    assert.equal(JSON.parse(await readFile(join(first, 'session-100.json'), 'utf8')).length, 100);
    assert.equal(JSON.parse(await readFile(join(first, 'session-10000.json'), 'utf8')).length, 10000);
    assert.equal((await readFile(join(first, 'diff-5mb.diff'))).length, 5 * 1024 * 1024);
    assert.equal((await readFile(join(first, 'diff-50mb-on-demand.diff'))).length, 50 * 1024 * 1024);
  } finally { await Promise.all([rm(first, { force: true, recursive: true }), rm(second, { force: true, recursive: true })]); }
});

test('validation rejects Vite/debug provenance and unexpected host paths', () => {
  const invalid = result({}, { build: 'debug', artifactSha256: 'a'.repeat(64), telemetry: 'enabled', hostPath: '/private/path' });
  const errors = validateBenchmarkResult(invalid);
  assert.ok(errors.length >= 3);
});

test('unsupported results may state unavailable provenance without inventing an artifact hash', () => {
  const unsupported = {
    schemaVersion: 1,
    status: 'unsupported',
    metadata: { os: 'linux', arch: 'x86_64', appVersion: 'unavailable', sidecarVersion: 'unavailable', dataset: 'unavailable', hardwareClass: 'unavailable' },
    provenance: { build: 'release-equivalent', artifactSha256: 'unavailable', telemetry: 'disabled' },
    measurements: [{ id: 'nativeReleaseRunner', status: 'unavailable', unit: 'none', reason: 'runner unavailable' }],
    attribution: [],
  };
  assert.deepEqual(validateBenchmarkResult(unsupported), []);
  assert.ok(validateBenchmarkResult({ ...unsupported, measurements: [] }).some((error) => error.includes('nativeReleaseRunner')));
});

test('normalizes each supported Node platform to the benchmark OS contract', () => {
  assert.equal(nodePlatformToBenchmarkOs('linux'), 'linux');
  assert.equal(nodePlatformToBenchmarkOs('win32'), 'windows');
  assert.equal(nodePlatformToBenchmarkOs('darwin'), 'macos');
  assert.throws(() => nodePlatformToBenchmarkOs('freebsd'), /Unsupported native benchmark platform/);
});

test('comparison warns at over ten percent and fails hard budgets', () => {
  const baseline = result({ firstWindowInteractiveColdP95: { value: 2000 } });
  const actual = result({ firstWindowInteractiveColdP95: { value: 3200 } });
  const evaluation = evaluateComparison(baseline, actual);
  assert.equal(evaluation.status, 'failed');
  assert.equal(evaluation.warnings.length, 1);
  assert.equal(evaluation.failures.length, 1);
  const report = renderComparisonReport(evaluation);
  assert.match(report, /60\.00% regression/);
  assert.match(report, /hard limit is 3000 ms/);
});

test('hard budgets fail for a canonical complete result', () => {
  const evaluation = evaluateComparison(result(), result({ linuxAppImage: { value: 262144001 } }));
  assert.equal(evaluation.status, 'failed');
  assert.equal(evaluation.comparisons.find((comparison) => comparison.id === 'linuxAppImage').status, 'compared');
  assert.equal(evaluation.failures[0].id, 'linuxAppImage');
});

test('invalid-input reports include validation evidence', () => {
  const evaluation = evaluateComparison(result(), { schemaVersion: 1 });
  assert.equal(evaluation.status, 'invalid');
  assert.match(renderComparisonReport(evaluation), /actual: .*required property 'metadata'/);
});

test('complete results fail closed for missing, unmeasured, wrongly-unit, and arbitrary metrics', () => {
  const missing = result();
  missing.measurements.pop();
  assert.ok(validateBenchmarkResult(missing).some((error) => error.includes('require measured')));
  const unavailable = result();
  unavailable.measurements[0] = { id: 'firstNativeWindowMs', status: 'unavailable', reason: 'missing runner' };
  assert.ok(validateBenchmarkResult(unavailable).some((error) => error.includes('require measured firstNativeWindowMs')));
  const badUnit = result({ firstPaintMs: { unit: 'bytes' } });
  assert.ok(validateBenchmarkResult(badUnit).some((error) => error.includes('must be ms')));
  const arbitrary = result();
  arbitrary.measurements[0] = { id: 'madeUpMetric', status: 'measured', value: 1, unit: 'count' };
  assert.ok(validateBenchmarkResult(arbitrary).some((error) => error.includes('canonical benchmark metric')));
});

test('comparison rejects OS, architecture, hardware class, and dataset mismatches', () => {
  for (const [key, value] of Object.entries({ os: 'windows', arch: 'arm64', hardwareClass: 'different', dataset: 'session-10000' })) {
    const evaluation = evaluateComparison(result(), result({}, undefined, { [key]: value }));
    assert.equal(evaluation.status, 'invalid');
    assert.match(renderComparisonReport(evaluation), new RegExp(`${key} mismatch`));
  }
});

test('each supported target has a distinct valid complete metric set', () => {
  for (const platform of ['linux', 'windows', 'macos']) {
    const complete = result({}, undefined, { os: platform });
    assert.deepEqual(validateBenchmarkResult(complete), [], platform);
    assert.equal(complete.measurements.some((measurement) => measurement.id === 'linuxAppImage'), platform === 'linux');
    assert.equal(complete.measurements.some((measurement) => measurement.id === 'windowsInstallerCompressed'), platform === 'windows');
    assert.equal(complete.measurements.some((measurement) => measurement.id === 'macosInstallerCompressed'), platform === 'macos');
  }
});

test('schema-backed validator rejects adversarial duplicate IDs and incomplete attribution', () => {
  const duplicateMetric = result();
  duplicateMetric.measurements.push({ ...duplicateMetric.measurements[0], value: 1 });
  assert.ok(validateBenchmarkResult(duplicateMetric).some((error) => error.includes('must be unique')));
  const missingAttribution = result();
  missingAttribution.attribution = missingAttribution.attribution.filter((item) => item.category !== 'providerAdapter');
  assert.ok(validateBenchmarkResult(missingAttribution).some((error) => error.includes('providerAdapter attribution')));
  assert.doesNotThrow(() => validateBenchmarkResult({ measurements: [null], attribution: [null] }));
});

test('CLI validation uses the same schema contract for valid and invalid evidence', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'argus-bench-cli-'));
  try {
    const validPath = join(directory, 'valid.json');
    await writeFile(validPath, JSON.stringify(result()));
    const valid = await execute(process.execPath, [benchmarkCli, 'validate', '--input', validPath]);
    assert.match(valid.stdout, /"status":"valid"/);
    const invalid = result();
    invalid.measurements.push({ ...invalid.measurements[0] });
    const invalidPath = join(directory, 'invalid.json');
    await writeFile(invalidPath, JSON.stringify(invalid));
    await assert.rejects(execute(process.execPath, [benchmarkCli, 'validate', '--input', invalidPath]));
  } finally { await rm(directory, { force: true, recursive: true }); }
});

test('artifact attribution hashes actual supplied files without outputting their paths', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'argus-bench-artifact-'));
  try {
    await writeFile(join(directory, 'chunk.js'), 'console.log("chunk")');
    const attributes = await attributeArtifacts([{ id: 'web-initial', category: 'frontend-chunk', path: 'chunk.js' }], directory);
    assert.equal(attributes[0].bytes, Buffer.byteLength('console.log("chunk")'));
    assert.equal(attributes[0].fileName, 'chunk.js');
    assert.equal(JSON.stringify(attributes).includes(directory), false);
  } finally { await rm(directory, { force: true, recursive: true }); }
});

test('artifact attribution rejects a symlink that escapes the supplied root', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'argus-bench-root-'));
  const outside = await mkdtemp(join(tmpdir(), 'argus-bench-outside-'));
  try {
    const outsideFile = join(outside, 'secret-looking-artifact.bin');
    await writeFile(outsideFile, 'not an artifact to expose');
    await symlink(outsideFile, join(directory, 'escaped.bin'));
    await assert.rejects(attributeArtifacts([{ id: 'escape', path: 'escaped.bin' }], directory), /symbolic link|outside/);
  } finally { await Promise.all([rm(directory, { force: true, recursive: true }), rm(outside, { force: true, recursive: true })]); }
});
