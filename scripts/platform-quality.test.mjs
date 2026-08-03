import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import test from 'node:test';

import {
  hasEmbeddedWebViewBootstrapper,
  isSupportedTarget,
  parseVersion,
  versionAtLeast,
} from './platform-quality.mjs';

test('declared desktop targets exclude Linux ARM64 until its separate gate exists', () => {
  assert.equal(isSupportedTarget('win32', 'x64'), true);
  assert.equal(isSupportedTarget('darwin', 'x64'), true);
  assert.equal(isSupportedTarget('darwin', 'arm64'), true);
  assert.equal(isSupportedTarget('linux', 'x64'), true);
  assert.equal(isSupportedTarget('linux', 'arm64'), false);
});

test('platform version comparison handles unequal component counts', () => {
  assert.equal(versionAtLeast(parseVersion('12.0'), [12]), true);
  assert.equal(versionAtLeast(parseVersion('2.35'), [2, 35]), true);
  assert.equal(versionAtLeast(parseVersion('2.34.9'), [2, 35]), false);
});

test('native CI and bundle configuration cover every declared target and package family', async () => {
  const root = join(import.meta.dirname, '..');
  const [workflow, configSource] = await Promise.all([
    readFile(join(root, '.github/workflows/native-quality.yml'), 'utf8'),
    readFile(join(root, 'src-tauri/tauri.conf.json'), 'utf8'),
  ]);
  for (const target of ['x86_64-pc-windows-msvc', 'x86_64-apple-darwin', 'aarch64-apple-darwin', 'x86_64-unknown-linux-gnu']) {
    assert.match(workflow, new RegExp(target));
  }
  assert.match(workflow, /bundles: nsis/);
  assert.match(workflow, /bundles: app,dmg/);
  assert.match(workflow, /bundles: appimage,deb/);
  assert.match(workflow, /container: debian:stable-slim/);
  const config = JSON.parse(configSource);
  assert.equal(config.identifier, 'com.argus.desktop');
  assert.equal(hasEmbeddedWebViewBootstrapper(config), true);
  assert.equal(hasEmbeddedWebViewBootstrapper({}), false);
  assert.ok(config.bundle.icon.includes('icons/icon.icns'));
  assert.ok(config.bundle.icon.includes('icons/icon.ico'));
  assert.deepEqual(config.bundle.windows.webviewInstallMode, { type: 'embedBootstrapper', silent: true });
  assert.equal(config.bundle.macOS.minimumSystemVersion, '12.0');
  assert.equal(config.app.windows[0].zoomHotkeysEnabled, true);
});

test('desktop package icons have real platform formats and declared PNG dimensions', async () => {
  const iconRoot = join(import.meta.dirname, '..', 'src-tauri', 'icons');
  const [small, medium, large, icns, ico] = await Promise.all([
    readFile(join(iconRoot, '32x32.png')),
    readFile(join(iconRoot, '128x128.png')),
    readFile(join(iconRoot, '128x128@2x.png')),
    readFile(join(iconRoot, 'icon.icns')),
    readFile(join(iconRoot, 'icon.ico')),
  ]);
  assert.deepEqual([small.readUInt32BE(16), small.readUInt32BE(20)], [32, 32]);
  assert.deepEqual([medium.readUInt32BE(16), medium.readUInt32BE(20)], [128, 128]);
  assert.deepEqual([large.readUInt32BE(16), large.readUInt32BE(20)], [256, 256]);
  assert.equal(icns.subarray(0, 4).toString('ascii'), 'icns');
  assert.deepEqual([...ico.subarray(0, 4)], [0, 0, 1, 0]);
});
