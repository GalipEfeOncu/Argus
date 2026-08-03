import assert from 'node:assert/strict';
import test from 'node:test';

import { contrastRatio, evaluateAccessibilityStyles } from './accessibility-quality.mjs';

test('WCAG contrast calculation handles black, white, and identical colors', () => {
  assert.equal(contrastRatio('#000000', '#ffffff'), 21);
  assert.equal(contrastRatio('#123456', '#123456'), 1);
});

test('Argus semantic text, status, and focus tokens pass their contrast gates', async () => {
  const result = await evaluateAccessibilityStyles();
  assert.equal(result.status, 'passed', JSON.stringify(result.checks));
});
