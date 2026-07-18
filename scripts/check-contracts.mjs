#!/usr/bin/env node

import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const repositoryRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const generator = join(repositoryRoot, 'scripts', 'generate-contracts.mjs');
const generatedFiles = [
  'contracts/session-events.schema.json',
  'contracts/session-commands.schema.json',
  'contracts/openapi.json',
  'src/types/generated/session-events.ts',
  'src/types/generated/session-commands.ts',
  'src/types/generated/rest.ts',
];

async function generatedOutputsMatch(outputRoot) {
  const driftedFiles = [];

  for (const relativePath of generatedFiles) {
    const [tracked, regenerated] = await Promise.all([
      readFile(join(repositoryRoot, relativePath)),
      readFile(join(outputRoot, relativePath)),
    ]);

    if (!tracked.equals(regenerated)) {
      driftedFiles.push(relativePath);
    }
  }

  return driftedFiles;
}

async function main() {
  const outputRoot = await mkdtemp(join(repositoryRoot, '.argus-contract-check-'));

  try {
    execFileSync(process.execPath, [generator, '--output-dir', outputRoot], {
      cwd: repositoryRoot,
      stdio: 'inherit',
    });

    const driftedFiles = await generatedOutputsMatch(outputRoot);
    if (driftedFiles.length > 0) {
      console.error(`Generated contract drift detected: ${driftedFiles.join(', ')}`);
      process.exitCode = 1;
    }
  } finally {
    await rm(outputRoot, { force: true, recursive: true });
  }
}

await main();
