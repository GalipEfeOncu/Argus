#!/usr/bin/env node

import { execFile, spawn } from 'node:child_process';
import { chmod, lstat, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { arch, platform, release, tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { promisify } from 'node:util';

const execute = promisify(execFile);
const TAURI_CONFIG_PATH = fileURLToPath(new URL('../src-tauri/tauri.conf.json', import.meta.url));
const SUPPORTED_ARCHITECTURES = Object.freeze({
  darwin: new Set(['arm64', 'x64']),
  linux: new Set(['x64']),
  win32: new Set(['x64']),
});

export function isSupportedTarget(osName, architecture) {
  return SUPPORTED_ARCHITECTURES[osName]?.has(architecture) ?? false;
}

export function parseVersion(value) {
  return value.trim().split('.').map((part) => Number.parseInt(part, 10) || 0);
}

export function versionAtLeast(actual, minimum) {
  const length = Math.max(actual.length, minimum.length);
  for (let index = 0; index < length; index += 1) {
    const difference = (actual[index] ?? 0) - (minimum[index] ?? 0);
    if (difference !== 0) return difference > 0;
  }
  return true;
}

export function hasEmbeddedWebViewBootstrapper(config) {
  return config?.bundle?.windows?.webviewInstallMode?.type === 'embedBootstrapper';
}

async function command(command, args = []) {
  try {
    const result = await execute(command, args, { timeout: 15_000, windowsHide: true });
    return { available: true, output: `${result.stdout}${result.stderr}`.trim() };
  } catch (error) {
    return { available: false, output: error instanceof Error ? error.message : String(error) };
  }
}

async function terminateChild() {
  const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
    stdio: 'ignore',
    windowsHide: true,
  });
  await new Promise((resolve, reject) => {
    child.once('spawn', resolve);
    child.once('error', reject);
  });
  child.kill();
  await Promise.race([
    new Promise((resolve, reject) => {
      child.once('exit', resolve);
      child.once('error', reject);
    }),
    new Promise((_, reject) => setTimeout(() => reject(new Error('child process did not stop within five seconds')), 5_000)),
  ]);
}

async function webviewCheck(osName) {
  if (osName === 'darwin') {
    const version = await command('sw_vers', ['-productVersion']);
    const passed = version.available && versionAtLeast(parseVersion(version.output), [12]);
    return { passed, detail: passed ? `system WebKit on macOS ${version.output}` : 'macOS 12 or newer was not detected' };
  }
  if (osName === 'linux') {
    const webkit = await command('pkg-config', ['--modversion', 'webkit2gtk-4.1']);
    const libc = await command('ldd', ['--version']);
    const glibcMatch = libc.output.match(/(?:glibc|GLIBC|GNU libc|ldd \(.*\))[^\d]*(\d+\.\d+)/i)
      ?? libc.output.match(/(\d+\.\d+)/);
    const glibcSupported = libc.available && glibcMatch !== null && versionAtLeast(parseVersion(glibcMatch[1]), [2, 35]);
    return {
      passed: webkit.available && glibcSupported,
      detail: webkit.available && glibcSupported
        ? `WebKitGTK ${webkit.output}; glibc ${glibcMatch[1]}`
        : 'WebKitGTK 4.1 development metadata and glibc 2.35+ are required',
    };
  }
  const probe = await command('powershell', [
    '-NoProfile',
    '-NonInteractive',
    '-Command',
    "$keys = @('HKLM:\\SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{F1E7E7A4-017C-4B47-B81B-69A4F8E49E37}', 'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{F1E7E7A4-017C-4B47-B81B-69A4F8E49E37}'); if ($keys | Where-Object { Test-Path $_ }) { 'installed' } else { exit 1 }",
  ]);
  let embeddedBootstrapper = false;
  try {
    const config = JSON.parse(await readFile(TAURI_CONFIG_PATH, 'utf8'));
    embeddedBootstrapper = hasEmbeddedWebViewBootstrapper(config);
  } catch {
    embeddedBootstrapper = false;
  }
  return {
    passed: probe.available || embeddedBootstrapper,
    detail: probe.available
      ? 'WebView2 Runtime is installed; the Argus installer also embeds the bootstrapper'
      : embeddedBootstrapper
        ? 'WebView2 Runtime is absent on the build host; the embedded bootstrapper is configured and clean-client installation remains a pre-publish check'
        : 'WebView2 Runtime was not found and the embedded installer bootstrapper is not configured',
  };
}

function add(checks, id, passed, detail) {
  checks.push({ id, status: passed ? 'passed' : 'failed', detail });
}

export async function runPlatformQuality({ requireWebview = false } = {}) {
  const osName = platform();
  const architecture = arch();
  const checks = [];
  add(checks, 'supported-target', isSupportedTarget(osName, architecture), `${osName}/${architecture}`);

  const git = await command('git', ['--version']);
  checks.push({
    id: 'git-prerequisite',
    status: git.available ? 'passed' : 'optional',
    detail: git.available ? git.output : 'Git is unavailable; Argus must use its non-git snapshot fallback',
  });
  const shell = osName === 'win32'
    ? await command('powershell', ['-NoProfile', '-NonInteractive', '-Command', '$PSVersionTable.PSVersion.ToString()'])
    : await command('/bin/sh', ['-c', 'printf POSIX-shell']);
  add(checks, 'shell-prerequisite', shell.available, shell.available ? shell.output : 'A supported system shell was not found');

  const fixtureRoot = await mkdtemp(join(tmpdir(), 'argus-platform-quality-'));
  try {
    const unicodeDirectory = join(fixtureRoot, 'Çalışma alanı 🛠');
    await mkdir(unicodeDirectory);
    const unicodeFile = join(unicodeDirectory, 'örnek dosya.txt');
    await writeFile(unicodeFile, 'UTF-8 ✓\n', 'utf8');
    add(checks, 'path-encoding-spaces', (await readFile(unicodeFile, 'utf8')) === 'UTF-8 ✓\n', 'Unicode and spaces round-trip through native filesystem APIs');

    let longDirectory = fixtureRoot;
    for (let index = 0; index < 18; index += 1) longDirectory = join(longDirectory, `segment-${index.toString().padStart(2, '0')}-abcdefgh`);
    await mkdir(longDirectory, { recursive: true });
    const longFile = join(longDirectory, 'long-path.txt');
    await writeFile(longFile, 'long-path\n');
    add(checks, 'long-path', (await readFile(longFile, 'utf8')) === 'long-path\n' && longFile.length > 300, `native path length ${longFile.length}`);

    const caseMarker = join(fixtureRoot, 'ArgusCaseProbe');
    await writeFile(caseMarker, 'case');
    let caseSensitive = false;
    try {
      await lstat(join(fixtureRoot, 'arguscaseprobe'));
    } catch {
      caseSensitive = true;
    }
    checks.push({ id: 'case-behavior', status: 'passed', detail: caseSensitive ? 'case-sensitive filesystem detected' : 'case-insensitive filesystem detected' });

    const endings = join(fixtureRoot, 'line-endings.txt');
    await writeFile(endings, Buffer.from('LF\nCRLF\r\n', 'utf8'));
    add(checks, 'line-endings', (await readFile(endings)).equals(Buffer.from('LF\nCRLF\r\n')), 'LF and CRLF bytes are preserved');

    const executable = join(fixtureRoot, 'executable-probe');
    await writeFile(executable, '#!/bin/sh\nexit 0\n');
    if (osName === 'win32') {
      checks.push({ id: 'executable-bits', status: 'not-applicable', detail: 'Windows does not use POSIX executable mode bits' });
    } else {
      await chmod(executable, 0o700);
      add(checks, 'executable-bits', ((await lstat(executable)).mode & 0o111) !== 0, 'POSIX executable mode is retained');
    }

    const symlinkPath = join(fixtureRoot, 'link-probe');
    await symlink(unicodeFile, symlinkPath, 'file');
    add(checks, 'symlink-semantics', (await lstat(symlinkPath)).isSymbolicLink(), 'symbolic links remain identifiable without being followed');
  } finally {
    await rm(fixtureRoot, { recursive: true, force: true });
  }

  try {
    await terminateChild();
    add(checks, 'process-cancellation', true, 'child process terminated within five seconds');
  } catch (error) {
    add(checks, 'process-cancellation', false, error instanceof Error ? error.message : String(error));
  }

  const webview = await webviewCheck(osName);
  checks.push({ id: 'native-webview', status: webview.passed ? 'passed' : (requireWebview ? 'failed' : 'deferred'), detail: webview.detail });
  return {
    schemaVersion: 1,
    status: checks.some((check) => check.status === 'failed') ? 'failed' : 'passed',
    target: { os: osName, arch: architecture, release: release() },
    checks,
  };
}

async function main() {
  const outputIndex = process.argv.indexOf('--output');
  const outputPath = outputIndex >= 0 ? process.argv[outputIndex + 1] : undefined;
  const result = await runPlatformQuality({ requireWebview: process.argv.includes('--require-webview') });
  const content = `${JSON.stringify(result, null, 2)}\n`;
  if (outputPath) {
    await mkdir(dirname(outputPath), { recursive: true });
    await writeFile(outputPath, content, 'utf8');
  }
  process.stdout.write(content);
  if (result.status !== 'passed') process.exitCode = 1;
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) await main();
