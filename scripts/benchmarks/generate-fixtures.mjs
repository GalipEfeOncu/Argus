#!/usr/bin/env node

import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { FIXTURE_MANIFEST_PATH, loadJson } from './core.mjs';

const repositoryRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

function argumentValue(name) {
  const index = process.argv.indexOf(name);
  return index === -1 ? undefined : process.argv[index + 1];
}

function eventFor(sequence) {
  return {
    version: 1,
    eventId: `benchmark-event-${String(sequence).padStart(5, '0')}`,
    sessionId: 'benchmark-session',
    sequence,
    timestamp: new Date(Date.UTC(2026, 0, 1, 0, 0, sequence)).toISOString().replace('.000Z', 'Z'),
    actorId: `benchmark-agent-${sequence % 3}`,
    type: 'participant.status_changed',
    payload: {
      participantId: `benchmark-agent-${sequence % 3}`,
      participantKind: 'agent',
      status: sequence % 2 === 0 ? 'working' : 'idle',
    },
  };
}

function diffBytes(byteLength) {
  const line = 'diff --git a/benchmark.txt b/benchmark.txt\n+@@ -1 +1 @@\n+-before\n++after deterministic benchmark content\n';
  const repeated = line.repeat(Math.ceil(byteLength / Buffer.byteLength(line)));
  return Buffer.from(repeated.slice(0, byteLength), 'utf8');
}

async function main() {
  const outputDirectory = argumentValue('--output-dir');
  if (!outputDirectory) throw new Error('Usage: generate-fixtures.mjs --output-dir <directory> [--include-on-demand]');
  const includeOnDemand = process.argv.includes('--include-on-demand');
  const manifest = await loadJson(join(repositoryRoot, FIXTURE_MANIFEST_PATH));
  await mkdir(outputDirectory, { recursive: true });
  for (const fixture of manifest.fixtures) {
    if (fixture.onDemand && !includeOnDemand) continue;
    if (fixture.kind === 'session-events') {
      await writeFile(join(outputDirectory, `${fixture.id}.json`), `${JSON.stringify(Array.from({ length: fixture.eventCount }, (_, offset) => eventFor(offset + 1)), null, 2)}\n`);
    } else if (fixture.kind === 'diff') {
      await writeFile(join(outputDirectory, `${fixture.id}.diff`), diffBytes(fixture.byteLength));
    } else if (fixture.kind === 'scenario') {
      await writeFile(join(outputDirectory, `${fixture.id}.scenario.json`), `${JSON.stringify({ schemaVersion: 1, id: fixture.id, kind: fixture.kind, description: fixture.description }, null, 2)}\n`);
    } else {
      throw new Error(`Unsupported fixture kind: ${fixture.kind}`);
    }
  }
  await writeFile(join(outputDirectory, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  const fixturePath = (fixture) => {
    if (fixture.kind === 'session-events') return `${fixture.id}.json`;
    if (fixture.kind === 'diff') return `${fixture.id}.diff`;
    return `${fixture.id}.scenario.json`;
  };
  const written = await Promise.all(manifest.fixtures.filter((fixture) => !fixture.onDemand || includeOnDemand).map(async (fixture) => ({ id: fixture.id, bytes: (await readFile(join(outputDirectory, fixturePath(fixture)))).length })));
  process.stdout.write(`${JSON.stringify({ status: 'generated', fixtures: written })}\n`);
}

await main();
