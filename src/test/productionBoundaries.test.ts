import { expect, test } from 'vitest';
import websocketSource from '@/services/websocket.ts?raw';
import indexHtml from '../../index.html?raw';

test('the live websocket transport has no simulator dependency or implicit approval identity', () => {
  expect(websocketSource).not.toContain('eventSimulator');
  expect(websocketSource).not.toContain('active-approval');
  expect(websocketSource).toContain('sendApproval(approved: boolean, approvalId: string)');
});

test('the application shell uses local system typography without external font resources', () => {
  expect(indexHtml).not.toMatch(/fonts\.(?:googleapis|gstatic)\.com/iu);
  expect(indexHtml).not.toMatch(/<(?:link|script|img|source)\b[^>]*(?:href|src)=["']https?:\/\//iu);
});
