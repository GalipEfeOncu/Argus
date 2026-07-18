import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { lstat, readFile, realpath, stat } from 'node:fs/promises';
import { basename, relative, resolve } from 'node:path';
import Ajv2020 from 'ajv/dist/2020.js';

export const FIXTURE_MANIFEST_PATH = 'benchmarks/fixtures/manifest.json';
export const BENCHMARK_SCHEMA_PATH = 'benchmarks/schema/benchmark-result.schema.json';
const benchmarkSchema = JSON.parse(readFileSync(new URL('../../benchmarks/schema/benchmark-result.schema.json', import.meta.url), 'utf8'));
const benchmarkContract = benchmarkSchema['x-argus-contract'];

export const REQUIRED_METRICS = Object.freeze(benchmarkContract.metrics);

export const REQUIRED_METRIC_IDS = Object.freeze(Object.keys(REQUIRED_METRICS));
export const SUPPORTED_MEASUREMENT_IDS = Object.freeze([...REQUIRED_METRIC_IDS, ...benchmarkContract.unsupportedOnlyMetricIds]);
export const HARD_BUDGETS = Object.freeze(Object.fromEntries(
  Object.entries(REQUIRED_METRICS)
    .filter(([, metric]) => metric.hardLimit !== undefined)
    .map(([id, metric]) => [id, { limit: metric.hardLimit, unit: metric.unit }]),
));

/**
 * A release runner supplies this adapter only after it has a packaged native
 * artifact. Unsupported adapters must return an unavailable measurement rather
 * than guessing a value from Vite or a debug build.
 *
 * @typedef {{ id: string, collect: (context: object) => Promise<object> }} MeasurementAdapter
 */
export const REQUIRED_ADAPTER_IDS = Object.freeze([...new Set(REQUIRED_METRIC_IDS.map((id) => REQUIRED_METRICS[id].adapter))]);

export async function loadJson(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

export function requiredMetricIdsForPlatform(platform) {
  return REQUIRED_METRIC_IDS.filter((id) => !REQUIRED_METRICS[id].platforms || REQUIRED_METRICS[id].platforms.includes(platform));
}

export function nodePlatformToBenchmarkOs(nodePlatform) {
  const platforms = { linux: 'linux', win32: 'windows', darwin: 'macos' };
  if (!platforms[nodePlatform]) throw new Error(`Unsupported native benchmark platform: ${nodePlatform}`);
  return platforms[nodePlatform];
}

function contractErrors(result) {
  if (!result || typeof result !== 'object') return [{ instancePath: '', message: 'must be an object' }];
  const errors = [];
  const measurements = Array.isArray(result.measurements) ? result.measurements : [];
  const measurementById = new Map();
  for (const [index, rawMeasurement] of measurements.entries()) {
    const measurement = rawMeasurement && typeof rawMeasurement === 'object' ? rawMeasurement : {};
    if (measurementById.has(measurement.id)) errors.push({ instancePath: `/measurements/${index}/id`, message: 'must be unique' });
    measurementById.set(measurement.id, measurement);
    const metric = REQUIRED_METRICS[measurement.id];
    if (!metric && !benchmarkContract.unsupportedOnlyMetricIds.includes(measurement.id)) errors.push({ instancePath: `/measurements/${index}/id`, message: 'must be a canonical benchmark metric' });
    if (metric && measurement.unit !== metric.unit) errors.push({ instancePath: `/measurements/${index}/unit`, message: `must be ${metric.unit} for ${measurement.id}` });
  }
  const attribution = Array.isArray(result.attribution) ? result.attribution : [];
  const attributionIds = new Set();
  for (const [index, rawItem] of attribution.entries()) {
    const item = rawItem && typeof rawItem === 'object' ? rawItem : {};
    if (attributionIds.has(item.id)) errors.push({ instancePath: `/attribution/${index}/id`, message: 'must be unique' });
    attributionIds.add(item.id);
  }
  if (result.status !== 'complete') {
    const runner = measurementById.get('nativeReleaseRunner');
    if (!runner || runner.status !== 'unavailable' || typeof runner.reason !== 'string' || runner.reason.length === 0) {
      errors.push({ instancePath: '/measurements', message: 'unsupported results require nativeReleaseRunner as an unavailable measurement with a reason' });
    }
    return errors;
  }
  if (result.provenance?.artifactSha256 === 'unavailable') errors.push({ instancePath: '/provenance/artifactSha256', message: 'complete results require a SHA-256 artifact provenance' });
  const platform = result.metadata?.os;
  for (const id of requiredMetricIdsForPlatform(platform)) {
    if (measurementById.get(id)?.status !== 'measured') errors.push({ instancePath: '/measurements', message: `complete ${platform} results require measured ${id}` });
  }
  for (const [id, metric] of Object.entries(REQUIRED_METRICS)) {
    if (metric.platforms && !metric.platforms.includes(platform) && measurementById.has(id)) errors.push({ instancePath: '/measurements', message: `${id} is not valid for ${platform}` });
  }
  for (const id of benchmarkContract.unsupportedOnlyMetricIds) if (measurementById.has(id)) errors.push({ instancePath: '/measurements', message: `${id} is only valid for unsupported results` });
  for (const category of benchmarkContract.requiredAttributionCategories) {
    if (!attribution.some((item) => item && typeof item === 'object' && item.category === category && item.status === 'measured')) errors.push({ instancePath: '/attribution', message: `complete results require measured ${category} attribution` });
  }
  return errors;
}

const ajv = new Ajv2020({ allErrors: true, strict: false });
function validateArgusContract(enabled, result) {
  if (!enabled) return true;
  const errors = contractErrors(result);
  validateArgusContract.errors = errors;
  return errors.length === 0;
}
ajv.addKeyword({
  keyword: 'x-argus-contract-validator',
  type: 'object',
  schemaType: 'boolean',
  errors: true,
  validate: validateArgusContract,
});
const validateSchema = ajv.compile(benchmarkSchema);

export function validateBenchmarkResult(result) {
  if (validateSchema(result)) return [];
  return (validateSchema.errors ?? []).map((error) => `${error.instancePath || '/'} ${error.message}`);
}

export function evaluateComparison(baseline, actual) {
  const baselineErrors = validateBenchmarkResult(baseline);
  const actualErrors = validateBenchmarkResult(actual);
  if (baselineErrors.length || actualErrors.length) {
    return { status: 'invalid', errors: { baseline: baselineErrors, actual: actualErrors }, warnings: [], failures: [], comparisons: [] };
  }
  if (baseline.status !== 'complete' || actual.status !== 'complete') {
    return { status: 'unsupported', errors: [], warnings: [], failures: [], comparisons: [], reason: 'Only complete release results can be compared; unsupported results are not baselines.' };
  }
  const compatibilityKeys = ['os', 'arch', 'hardwareClass', 'dataset'];
  const incompatibilities = compatibilityKeys
    .filter((key) => baseline.metadata[key] !== actual.metadata[key])
    .map((key) => `${key} mismatch: baseline=${baseline.metadata[key]}, actual=${actual.metadata[key]}`);
  if (incompatibilities.length) {
    return { status: 'invalid', errors: { baseline: [], actual: [], comparison: incompatibilities }, warnings: [], failures: [], comparisons: [] };
  }
  const baselineById = new Map(baseline.measurements.map((measurement) => [measurement.id, measurement]));
  const warnings = [];
  const failures = [];
  const comparisons = actual.measurements.map((measurement) => {
    const previous = baselineById.get(measurement.id);
    const budget = HARD_BUDGETS[measurement.id];
    if (measurement.status === 'measured' && budget && (budget.unit !== measurement.unit || measurement.value > budget.limit)) {
      failures.push({ id: measurement.id, actual: measurement.value, unit: measurement.unit, limit: budget.limit, expectedUnit: budget.unit });
    }
    if (!previous || previous.status !== 'measured' || measurement.status !== 'measured' || previous.unit !== measurement.unit) {
      return { id: measurement.id, status: 'unavailable', actual: measurement, baseline: previous ?? null, reason: 'A comparable measured baseline with the same unit is unavailable.' };
    }
    const regressionPercent = previous.value === 0 ? (measurement.value === 0 ? 0 : null) : ((measurement.value - previous.value) / previous.value) * 100;
    const comparison = { id: measurement.id, status: 'compared', actual: measurement, baseline: previous, regressionPercent };
    if (regressionPercent !== null && regressionPercent > 10) warnings.push({ id: measurement.id, regressionPercent });
    return comparison;
  });
  return { status: failures.length ? 'failed' : 'passed', errors: [], warnings, failures, comparisons };
}

export function renderComparisonReport(evaluation) {
  const lines = ['# Argus release benchmark comparison', ''];
  lines.push(`Outcome: **${evaluation.status}**`);
  if (evaluation.reason) lines.push('', evaluation.reason);
  if (Object.values(evaluation.errors).some((errors) => errors.length)) lines.push('', '## Invalid input', '', ...Object.entries(evaluation.errors).flatMap(([source, errors]) => errors.map((error) => `- ${source}: ${error}`)));
  if (evaluation.comparisons.length) {
    lines.push('', '## Measurements', '', '| Metric | Baseline | Actual | Regression | Status |', '| --- | ---: | ---: | ---: | --- |');
    for (const item of evaluation.comparisons) {
      if (item.status === 'compared') lines.push(`| ${item.id} | ${item.baseline.value} ${item.baseline.unit} | ${item.actual.value} ${item.actual.unit} | ${item.regressionPercent === null ? 'n/a' : `${item.regressionPercent.toFixed(2)}%`} | compared |`);
      else lines.push(`| ${item.id} | ${item.baseline?.status === 'measured' ? `${item.baseline.value} ${item.baseline.unit}` : 'unavailable'} | ${item.actual?.status === 'measured' ? `${item.actual.value} ${item.actual.unit}` : 'unavailable'} | n/a | unavailable |`);
    }
  }
  if (evaluation.warnings.length) lines.push('', '## Regression warnings', '', ...evaluation.warnings.map((warning) => `- ${warning.id}: ${warning.regressionPercent.toFixed(2)}% regression exceeds the 10% warning threshold.`));
  if (evaluation.failures.length) lines.push('', '## Hard budget failures', '', ...evaluation.failures.map((failure) => `- ${failure.id}: ${failure.actual} ${failure.unit}; hard limit is ${failure.limit} ${failure.expectedUnit}.`));
  return `${lines.join('\n')}\n`;
}

export async function attributeArtifacts(artifacts, repositoryRoot) {
  if (!Array.isArray(artifacts)) throw new Error('artifact input must be an array');
  const root = await realpath(resolve(repositoryRoot));
  const seen = new Set();
  const output = [];
  for (const artifact of artifacts) {
    if (!artifact || typeof artifact.id !== 'string' || typeof artifact.path !== 'string' || artifact.id.length === 0) throw new Error('each artifact needs a non-empty id and path');
    if (seen.has(artifact.id)) throw new Error(`duplicate artifact id: ${artifact.id}`);
    seen.add(artifact.id);
    const resolved = resolve(root, artifact.path);
    if (relative(root, resolved).startsWith('..')) throw new Error(`artifact ${artifact.id} must stay below the supplied artifact root`);
    const linkStat = await lstat(resolved);
    if (linkStat.isSymbolicLink()) throw new Error(`artifact ${artifact.id} may not be a symbolic link`);
    const realFile = await realpath(resolved);
    if (relative(root, realFile).startsWith('..')) throw new Error(`artifact ${artifact.id} resolves outside the supplied artifact root`);
    const file = await readFile(realFile);
    const fileStat = await stat(realFile);
    if (!fileStat.isFile()) throw new Error(`artifact ${artifact.id} must be a file`);
    output.push({ id: artifact.id, category: typeof artifact.category === 'string' ? artifact.category : 'unclassified', fileName: basename(realFile), bytes: file.length, sha256: createHash('sha256').update(file).digest('hex') });
  }
  return output;
}
