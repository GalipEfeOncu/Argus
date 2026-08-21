import { readdir, readFile } from 'node:fs/promises';
import { extname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const scannedExtensions = new Set(['.css', '.html', '.js']);
const forbiddenPatterns = [
  { label: 'Google Fonts domain', extensions: scannedExtensions, expression: /fonts\.(?:googleapis|gstatic)\.com/iu },
  { label: 'external HTML asset', extensions: new Set(['.html']), expression: /<(?:link|script|img|source)\b[^>]*(?:href|src)=["']https?:\/\//iu },
  { label: 'external CSS import', extensions: new Set(['.css']), expression: /@import\s+(?:url\()?\s*["']?https?:\/\//iu },
  { label: 'external CSS asset', extensions: new Set(['.css']), expression: /url\(\s*["']?https?:\/\//iu },
];

async function filesUnder(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await filesUnder(path));
    else if (entry.isFile() && scannedExtensions.has(extname(entry.name))) files.push(path);
  }
  return files;
}

export async function assertOfflineAssets(directory) {
  const root = resolve(directory);
  let builtCss = '';
  for (const path of await filesUnder(root)) {
    const content = await readFile(path, 'utf8');
    if (extname(path) === '.css') builtCss += content;
    for (const { label, extensions, expression } of forbiddenPatterns) {
      if (!extensions.has(extname(path))) continue;
      if (expression.test(content)) throw new Error(`${label} found in ${path.slice(root.length + 1)}`);
    }
  }
  if (!/--font-sans:\s*ui-sans-serif,\s*system-ui/iu.test(builtCss) || !/--font-mono:\s*ui-monospace/iu.test(builtCss)) {
    throw new Error('Built CSS is missing the local system typography tokens.');
  }
  if (/["'](?:Inter|JetBrains Mono)["']/iu.test(builtCss)) throw new Error('Built CSS contains an external font-family dependency.');
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const directory = process.argv[2];
  if (!directory) throw new Error('Usage: check-offline-assets.mjs <build-directory>');
  await assertOfflineAssets(directory);
  console.log('Offline asset checks OK');
}
