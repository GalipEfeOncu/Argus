import { expect, test } from 'vitest';
import type { ArgusSessionCommand } from '@/types/generated/session-commands';
import type { ArgusSessionEvent } from '@/types/generated/session-events';

test('generated canonical event and command unions are consumable by frontend tests', () => {
  const event: ArgusSessionEvent = {
    version: 1,
    eventId: 'evt_01',
    sessionId: 'ses_01',
    sequence: 0,
    timestamp: '2026-01-01T00:00:00Z',
    type: 'session.status_changed',
    actorId: 'sys_01',
    payload: { status: 'running' },
  };
  const command: ArgusSessionCommand = {
    commandId: 'cmd_01',
    type: 'message.send',
    payload: { content: 'Use the generated contract.' },
  };

  expect(event.type).toBe('session.status_changed');
  expect(command.type).toBe('message.send');
});
