import { expect, test } from 'vitest';
import { highlightDiffMetadata } from '@/services/diffEnhancement';

test('the bounded Shiki core preserves escaped plain-text preview output', async () => {
  const html = await highlightDiffMetadata('Diff <tag> & metadata');

  expect(html).toContain('class="shiki github-dark"');
  expect(html).toContain('Diff &#x3C;tag> &#x26; metadata');
  expect(html).not.toContain('<tag>');
});
