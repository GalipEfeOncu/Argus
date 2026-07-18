#!/usr/bin/env node

import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { attributeArtifacts, evaluateComparison, loadJson, nodePlatformToBenchmarkOs, renderComparisonReport, validateBenchmarkResult } from './core.mjs';

const repositoryRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const command = process.argv[2];

function option(name) {
  const index = process.argv.indexOf(name);
  return index === -1 ? undefined : process.argv[index + 1];
}

async function writeOutput(path, content) {
  if (!path) return;
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, content);
}

async function main() {
  if (command === 'validate') {
    const input = option('--input');
    if (!input) throw new Error('Usage: benchmark.mjs validate --input <result.json>');
    const errors = validateBenchmarkResult(await loadJson(input));
    process.stdout.write(`${JSON.stringify({ status: errors.length ? 'invalid' : 'valid', errors })}\n`);
    if (errors.length) process.exitCode = 1;
    return;
  }
  if (command === 'compare' || command === 'report') {
    const baselinePath = option('--baseline');
    const actualPath = option('--actual');
    if (!baselinePath || !actualPath) throw new Error(`Usage: benchmark.mjs ${command} --baseline <baseline.json> --actual <actual.json> [--output <path>]`);
    const result = evaluateComparison(await loadJson(baselinePath), await loadJson(actualPath));
    if (command === 'report') {
      const report = renderComparisonReport(result);
      await writeOutput(option('--output'), report);
      process.stdout.write(report);
    } else {
      const content = `${JSON.stringify(result, null, 2)}\n`;
      await writeOutput(option('--output'), content);
      process.stdout.write(content);
    }
    if (result.status === 'invalid' || result.status === 'failed') process.exitCode = 1;
    return;
  }
  if (command === 'attribution') {
    const input = option('--input');
    if (!input) throw new Error('Usage: benchmark.mjs attribution --input <artifacts.json>');
    const artifacts = await loadJson(input);
    const result = await attributeArtifacts(artifacts, repositoryRoot);
    const content = `${JSON.stringify({ artifacts: result }, null, 2)}\n`;
    await writeOutput(option('--output'), content);
    process.stdout.write(content);
    return;
  }
  if (command === 'release') {
    const result = {
      schemaVersion: 1,
      status: 'unsupported',
      metadata: { os: nodePlatformToBenchmarkOs(process.platform), arch: process.arch, appVersion: 'unavailable', sidecarVersion: 'unavailable', dataset: 'unavailable', hardwareClass: 'unavailable' },
      provenance: { build: 'release-equivalent', artifactSha256: 'unavailable', telemetry: 'disabled' },
      measurements: [{ id: 'nativeReleaseRunner', status: 'unavailable', unit: 'none', reason: 'A native packaged Tauri and sidecar benchmark runner is not configured on this host.' }],
      attribution: [],
    };
    const content = `${JSON.stringify(result, null, 2)}\n`;
    await writeOutput(option('--output'), content);
    process.stdout.write(content);
    process.exitCode = 2;
    return;
  }
  throw new Error('Usage: benchmark.mjs {validate|compare|report|attribution|release} ...');
}

await main();
