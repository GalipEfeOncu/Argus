#!/usr/bin/env node

import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const repositoryRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const paths = {
  packageJson: join(repositoryRoot, 'package.json'),
  packageLock: join(repositoryRoot, 'package-lock.json'),
  cargoManifest: join(repositoryRoot, 'src-tauri', 'Cargo.toml'),
  cargoLock: join(repositoryRoot, 'src-tauri', 'Cargo.lock'),
  tauriConfig: join(repositoryRoot, 'src-tauri', 'tauri.conf.json'),
  backendManifest: join(repositoryRoot, 'backend', 'pyproject.toml'),
  backendVersion: join(repositoryRoot, 'backend', 'app', 'version.py'),
  backendLock: join(repositoryRoot, 'backend', 'uv.lock'),
};

const semverPattern = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;

function parseJson(text, path) {
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`Cannot parse ${path}: ${error.message}`);
  }
}

function tomlSection(text, heading) {
  const marker = `[${heading}]`;
  const start = text.indexOf(marker);
  if (start < 0) {
    throw new Error(`Missing TOML section ${marker}`);
  }
  const next = text.indexOf('\n[', start + marker.length);
  const end = next < 0 ? text.length : next;
  return { start, end, text: text.slice(start, end) };
}

function cargoPackageBlock(text) {
  const blocks = text.split(/(?=^\[\[package\]\]$)/m);
  const block = blocks.find((candidate) => /^name = "argus"$/m.test(candidate));
  if (!block) {
    throw new Error('Missing Argus package in src-tauri/Cargo.lock');
  }
  return block;
}

function backendPackageBlock(text) {
  const blocks = text.split(/(?=^\[\[package\]\]$)/m);
  const block = blocks.find((candidate) => /^name = "argus-backend"$/m.test(candidate));
  if (!block) throw new Error('Missing argus-backend package in backend/uv.lock');
  return block;
}

function versionFromCargoPackage(block) {
  const match = block.match(/^version\s*=\s*"([^"]+)"$/m);
  if (!match) {
    throw new Error('Missing Argus version in src-tauri/Cargo.lock');
  }
  return match[1];
}

function replaceCargoPackageVersion(block, version) {
  const pattern = /^version\s*=\s*"[^"]+"$/m;
  if (!pattern.test(block)) {
    throw new Error('Missing Argus version in src-tauri/Cargo.lock');
  }
  return block.replace(
    pattern,
    `version = "${version}"`,
  );
}

function versionFromToml(text, heading) {
  const section = tomlSection(text, heading).text;
  const match = section.match(/^version\s*=\s*"([^"]+)"$/m);
  if (!match) {
    throw new Error(`Missing version in TOML section [${heading}]`);
  }
  return match[1];
}

function replaceSectionVersion(text, heading, version) {
  const section = tomlSection(text, heading);
  const pattern = /^version\s*=\s*"[^"]+"$/m;
  if (!pattern.test(section.text)) {
    throw new Error(`Missing version in TOML section [${heading}]`);
  }
  const updated = section.text.replace(
    pattern,
    `version = "${version}"`,
  );
  return text.slice(0, section.start) + updated + text.slice(section.end);
}

function versionFromPython(text) {
  const match = text.match(/^APP_VERSION\s*=\s*"([^"]+)"$/m);
  if (!match) throw new Error('Missing APP_VERSION in backend/app/version.py');
  return match[1];
}

function replacePythonVersion(text, version) {
  return text.replace(/^APP_VERSION\s*=\s*"[^"]+"$/m, `APP_VERSION = "${version}"`);
}

async function readSources() {
  const [packageText, lockText, cargoText, cargoLockText, tauriText, backendManifestText, backendVersionText, backendLockText] = await Promise.all([
    readFile(paths.packageJson, 'utf8'),
    readFile(paths.packageLock, 'utf8'),
    readFile(paths.cargoManifest, 'utf8'),
    readFile(paths.cargoLock, 'utf8'),
    readFile(paths.tauriConfig, 'utf8'),
    readFile(paths.backendManifest, 'utf8'),
    readFile(paths.backendVersion, 'utf8'),
    readFile(paths.backendLock, 'utf8'),
  ]);
  return {
    packageText,
    lockText,
    cargoText,
    cargoLockText,
    tauriText,
    packageJson: parseJson(packageText, 'package.json'),
    packageLock: parseJson(lockText, 'package-lock.json'),
    tauriConfig: parseJson(tauriText, 'src-tauri/tauri.conf.json'),
    backendManifestText,
    backendVersionText,
    backendLockText,
  };
}

function collectVersions(sources) {
  const lockRoot = sources.packageLock.packages?.['']?.version;
  const cargoLockBlock = cargoPackageBlock(sources.cargoLockText);
  return new Map([
    ['package.json', sources.packageJson.version],
    ['package-lock.json', sources.packageLock.version],
    ['package-lock.json root package', lockRoot],
    ['src-tauri/Cargo.toml', versionFromToml(sources.cargoText, 'package')],
    ['src-tauri/Cargo.lock', versionFromCargoPackage(cargoLockBlock)],
    ['src-tauri/tauri.conf.json', sources.tauriConfig.version],
    ['backend/pyproject.toml', versionFromToml(sources.backendManifestText, 'project')],
    ['backend/app/version.py', versionFromPython(sources.backendVersionText)],
    ['backend/uv.lock', versionFromCargoPackage(backendPackageBlock(sources.backendLockText))],
  ]);
}

function validateVersion(version) {
  if (typeof version !== 'string' || !semverPattern.test(version)) {
    throw new Error(`Invalid Semantic Version: ${String(version)}`);
  }
}

async function check() {
  const versions = collectVersions(await readSources());
  const expected = versions.get('package.json');
  validateVersion(expected);
  const drift = [...versions].filter(([, version]) => version !== expected);
  if (drift.length > 0) {
    const details = drift.map(([source, version]) => `${source}=${String(version)}`).join(', ');
    throw new Error(`Version drift from package.json=${expected}: ${details}`);
  }
  console.log(`Version sync OK: ${expected}`);
}

async function setVersion(version) {
  validateVersion(version);
  const sources = await readSources();
  sources.packageJson.version = version;
  sources.packageLock.version = version;
  if (!sources.packageLock.packages?.['']) {
    throw new Error('Missing root package entry in package-lock.json');
  }
  sources.packageLock.packages[''].version = version;
  sources.tauriConfig.version = version;

  const cargoLockBlock = cargoPackageBlock(sources.cargoLockText);
  const updatedCargoLockBlock = replaceCargoPackageVersion(cargoLockBlock, version);
  const updatedCargoLock = sources.cargoLockText.replace(cargoLockBlock, updatedCargoLockBlock);
  const backendLockBlock = backendPackageBlock(sources.backendLockText);
  const updatedBackendLock = sources.backendLockText.replace(
    backendLockBlock,
    replaceCargoPackageVersion(backendLockBlock, version),
  );

  await Promise.all([
    writeFile(paths.packageJson, `${JSON.stringify(sources.packageJson, null, 2)}\n`),
    writeFile(paths.packageLock, `${JSON.stringify(sources.packageLock, null, 2)}\n`),
    writeFile(paths.cargoManifest, replaceSectionVersion(sources.cargoText, 'package', version)),
    writeFile(paths.cargoLock, updatedCargoLock),
    writeFile(paths.tauriConfig, `${JSON.stringify(sources.tauriConfig, null, 2)}\n`),
    writeFile(paths.backendManifest, replaceSectionVersion(sources.backendManifestText, 'project', version)),
    writeFile(paths.backendVersion, replacePythonVersion(sources.backendVersionText, version)),
    writeFile(paths.backendLock, updatedBackendLock),
  ]);
  await check();
}

const [command = 'check', version, ...extra] = process.argv.slice(2);
if (extra.length > 0 || (command !== 'check' && command !== 'set')) {
  throw new Error('Usage: node scripts/version.mjs check | set <version>');
}
if (command === 'set') {
  if (!version) {
    throw new Error('Usage: node scripts/version.mjs set <version>');
  }
  await setVersion(version);
} else {
  if (version) {
    throw new Error('Usage: node scripts/version.mjs check');
  }
  await check();
}
