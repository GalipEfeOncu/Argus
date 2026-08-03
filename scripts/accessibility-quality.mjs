#!/usr/bin/env node

import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const repositoryRoot = join(dirname(fileURLToPath(import.meta.url)), '..');

export function relativeLuminance(hex) {
  const channels = hex.slice(1).match(/../g)?.map((channel) => Number.parseInt(channel, 16) / 255);
  if (!channels || channels.length !== 3) throw new Error(`Invalid six-digit color: ${hex}`);
  const linear = channels.map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

export function contrastRatio(foreground, background) {
  const values = [relativeLuminance(foreground), relativeLuminance(background)].sort((left, right) => right - left);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

function parseTokens(source) {
  return Object.fromEntries([...source.matchAll(/--([a-z0-9-]+):\s*(#[a-f0-9]{6})\s*;/gi)].map((match) => [match[1], match[2]]));
}

export async function evaluateAccessibilityStyles() {
  const [tokensSource, animationsSource, htmlSource, tauriConfigSource, capabilitySource] = await Promise.all([
    readFile(join(repositoryRoot, 'src/styles/tokens.css'), 'utf8'),
    readFile(join(repositoryRoot, 'src/styles/animations.css'), 'utf8'),
    readFile(join(repositoryRoot, 'index.html'), 'utf8'),
    readFile(join(repositoryRoot, 'src-tauri/tauri.conf.json'), 'utf8'),
    readFile(join(repositoryRoot, 'src-tauri/capabilities/default.json'), 'utf8'),
  ]);
  const tokens = parseTokens(tokensSource);
  const pairs = [
    ['text-primary', 'bg-main', 4.5],
    ['text-secondary', 'bg-main', 4.5],
    ['text-muted', 'bg-main', 4.5],
    ['accent-text', 'bg-main', 4.5],
    ['accent-text', 'bg-card', 4.5],
    ['accent-text-hover', 'bg-main', 4.5],
    ['status-success', 'bg-card', 4.5],
    ['status-warning', 'bg-card', 4.5],
    ['status-error', 'bg-card', 4.5],
    ['border-focus', 'bg-main', 3],
    ['text-inverse', 'status-warning', 4.5],
    ['text-inverse', 'status-error', 4.5],
    ['text-primary', 'status-idle', 4.5],
    ['text-primary', 'accent-primary', 4.5],
    ['text-primary', 'accent-hover', 4.5],
  ];
  const checks = pairs.map(([foregroundName, backgroundName, minimum]) => {
    const ratio = contrastRatio(tokens[foregroundName], tokens[backgroundName]);
    return {
      id: `contrast-${foregroundName}-${backgroundName}`,
      status: ratio >= minimum ? 'passed' : 'failed',
      detail: `${ratio.toFixed(2)}:1 (minimum ${minimum}:1)`,
    };
  });
  checks.push({
    id: 'global-reduced-motion',
    status: /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*animation-duration:\s*0\.01ms\s*!important[\s\S]*transition-duration:\s*0\.01ms\s*!important/.test(animationsSource) ? 'passed' : 'failed',
    detail: 'global animation and transition suppression is present',
  });
  const tauriConfig = JSON.parse(tauriConfigSource);
  const capability = JSON.parse(capabilitySource);
  const zoomEnabled = tauriConfig.app.windows.every((window) => window.zoomHotkeysEnabled === true)
    && capability.permissions.includes('core:webview:allow-set-webview-zoom')
    && /name="viewport"\s+content="(?![^"]*(?:user-scalable=no|maximum-scale=1))/.test(htmlSource);
  checks.push({
    id: 'user-zoom',
    status: zoomEnabled ? 'passed' : 'failed',
    detail: 'native zoom hotkeys and scalable viewport are enabled',
  });
  return { schemaVersion: 1, status: checks.some((check) => check.status === 'failed') ? 'failed' : 'passed', checks };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const result = await evaluateAccessibilityStyles();
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (result.status !== 'passed') process.exitCode = 1;
}
