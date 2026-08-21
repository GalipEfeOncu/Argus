import { expect, test } from 'vitest';
import websocketSource from '@/services/websocket.ts?raw';

test('the live websocket transport has no simulator dependency or implicit approval identity', () => {
  expect(websocketSource).not.toContain('eventSimulator');
  expect(websocketSource).not.toContain('active-approval');
  expect(websocketSource).toContain('sendApproval(approved: boolean, approvalId: string)');
});
