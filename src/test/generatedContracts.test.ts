import { expect, test } from 'vitest';
import type {
  ArgusSessionCommand,
  ArgusSessionEvent,
} from '@/types/events';
import type { ArgusSessionCommand as GeneratedArgusSessionCommand } from '@/types/generated/session-commands';
import type { ArgusSessionEvent as GeneratedArgusSessionEvent } from '@/types/generated/session-events';

type IsExactly<Left, Right> = (<Value>() => Value extends Left ? 1 : 2) extends
  <Value>() => Value extends Right ? 1 : 2
  ? (<Value>() => Value extends Right ? 1 : 2) extends <Value>() => Value extends Left ? 1 : 2
    ? true
    : false
  : false;
type Assert<Type extends true> = Type;

const canonicalReexportsMatchGenerated: [
  Assert<IsExactly<ArgusSessionEvent, GeneratedArgusSessionEvent>>,
  Assert<IsExactly<ArgusSessionCommand, GeneratedArgusSessionCommand>>,
] = [true, true];
void canonicalReexportsMatchGenerated;

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
