import { expect, test } from 'vitest';
import type { ArgusSessionEvent } from '@/types/events';
import { createSessionProjection, reduceSessionEvent } from '@/services/sessionProjection';
import { InMemorySessionTransport, parseSessionEvent, SessionStreamClient } from '@/services/sessionTransport';
import { FakeClock } from './helpers/simulatorScenario';

const sessionId = 'ses_projection';

function event<T extends ArgusSessionEvent['type']>(
  sequence: number,
  type: T,
  payload: Extract<ArgusSessionEvent, { type: T }>['payload'],
  overrides: Partial<ArgusSessionEvent> = {},
): Extract<ArgusSessionEvent, { type: T }> {
  return {
    version: 1,
    eventId: `evt_${sequence}_${type}`,
    sessionId,
    sequence,
    timestamp: '2026-07-19T12:00:00Z',
    actorId: 'system',
    type,
    payload,
    ...overrides,
  } as Extract<ArgusSessionEvent, { type: T }>;
}

function snapshot(lastSequence = 0) {
  return event(0, 'session.snapshot', { status: 'running', lastSequence });
}

test('projection accepts an initial snapshot and drains a future sequence buffer in order', () => {
  let state = createSessionProjection(sessionId);
  state = reduceSessionEvent(state, snapshot()).state;
  const third = event(3, 'message.completed', { messageId: 'msg_1' });
  const second = event(2, 'message.delta', { messageId: 'msg_1', delta: ' world' });
  const first = event(1, 'message.created', {
    messageId: 'msg_1', authorId: 'coordinator', authorKind: 'coordinator', content: 'hello', streaming: true,
  });

  state = reduceSessionEvent(state, third).state;
  state = reduceSessionEvent(state, first).state;
  state = reduceSessionEvent(state, second).state;

  expect(state.lastSequence).toBe(3);
  expect(state.events.map((entry) => entry.sequence)).toEqual([1, 2, 3]);
  expect(state.messages.msg_1).toMatchObject({ content: 'hello world', streaming: false });
});

test('projection ignores exact duplicate events but requires resync for a conflicting event ID', () => {
  const first = event(1, 'session.status_changed', { status: 'paused' });
  let state = reduceSessionEvent(createSessionProjection(sessionId), snapshot()).state;
  state = reduceSessionEvent(state, first).state;

  expect(reduceSessionEvent(state, first).disposition).toBe('ignored');
  const conflicting = { ...first, payload: { status: 'running' as const } };
  const result = reduceSessionEvent(state, conflicting);
  expect(result.disposition).toBe('resync_required');
  expect(result.state.resyncReason).toBe('conflicting_event');
});

test('projection requires resync for a different event at an already applied sequence', () => {
  let state = reduceSessionEvent(createSessionProjection(sessionId), snapshot()).state;
  state = reduceSessionEvent(state, event(1, 'session.status_changed', { status: 'paused' })).state;
  const conflictingSequence = event(1, 'session.status_changed', { status: 'running' }, { eventId: 'evt_other' });

  const result = reduceSessionEvent(state, conflictingSequence);
  expect(result.disposition).toBe('resync_required');
  expect(result.state.resyncReason).toBe('conflicting_sequence');
});

test('parser rejects invalid canonical payload values and unexpected nested fields', () => {
  expect(parseSessionEvent({
    ...snapshot(),
    payload: { status: 'not-a-status', lastSequence: '0' },
  })).toBeNull();
  expect(parseSessionEvent({
    ...event(1, 'artifact.diff_updated', {
      artifactId: 'art_1', filePath: 'src/app.ts', additions: 1, deletions: 0, byteLength: 10,
    }),
    payload: { artifactId: 'art_1', filePath: '../secret.ts', additions: 1, deletions: 0, byteLength: 10 },
  })).toBeNull();
  expect(parseSessionEvent({
    ...snapshot(),
    timestamp: '2026-99-99T99:99:99Z',
  })).toBeNull();
});

test('client reconnects from the last applied sequence and resyncs malformed payloads', () => {
  const clock = new FakeClock();
  const transport = new InMemorySessionTransport();
  const client = new SessionStreamClient(transport, sessionId, clock, 10);
  client.connect();
  transport.emit(snapshot());
  transport.emit(event(1, 'session.status_changed', { status: 'paused' }));
  client.disconnect();
  client.connect();

  expect(transport.connections.at(-1)).toEqual({ sessionId, afterSequence: 1 });
  transport.emit({ version: 1, type: 'message.created' });
  expect(client.getProjection().resyncReason).toBe('invalid_payload');
  expect(transport.connections.at(-1)).toEqual({ sessionId, afterSequence: 1 });
});

test('client requests resync after a sequence gap timeout', () => {
  const clock = new FakeClock();
  const transport = new InMemorySessionTransport();
  const client = new SessionStreamClient(transport, sessionId, clock, 10);
  client.connect();
  transport.emit(snapshot());
  transport.emit(event(2, 'session.status_changed', { status: 'paused' }));
  clock.advanceBy(10);

  expect(client.getProjection().resyncReason).toBe('sequence_gap');
  expect(transport.connections.at(-1)).toEqual({ sessionId, afterSequence: 0 });
});

test('pending commands retry with the same idempotency key and resolve only from a correlated event', () => {
  const transport = new InMemorySessionTransport();
  const client = new SessionStreamClient(transport, sessionId);
  client.connect();
  transport.emit(snapshot());
  const command = { commandId: 'cmd_pause', type: 'session.pause' as const, payload: {} };

  client.send(command);
  client.retry(command.commandId);
  expect(transport.sentCommands.map((entry) => entry.commandId)).toEqual(['cmd_pause', 'cmd_pause']);
  expect(client.getProjection().pendingCommands.cmd_pause?.attempts).toBe(2);

  transport.emit(event(1, 'session.status_changed', { status: 'paused' }, { correlationId: command.commandId }));
  expect(client.getProjection().pendingCommands.cmd_pause).toBeUndefined();
  expect(client.getProjection().status).toBe('paused');
});

test('stale snapshots cannot overwrite newer projected state', () => {
  let state = reduceSessionEvent(createSessionProjection(sessionId), snapshot()).state;
  state = reduceSessionEvent(state, event(1, 'session.status_changed', { status: 'paused' })).state;
  const stale = event(0, 'session.snapshot', { status: 'running', lastSequence: 0 }, { eventId: 'evt_stale' });

  const result = reduceSessionEvent(state, stale);
  expect(result.disposition).toBe('ignored');
  expect(result.state.status).toBe('paused');
});

test('a newer snapshot does not skip replay events that rebuild the projection', () => {
  let state = reduceSessionEvent(createSessionProjection(sessionId), snapshot()).state;
  state = reduceSessionEvent(state, event(1, 'session.status_changed', { status: 'paused' })).state;
  state = reduceSessionEvent(state, event(0, 'session.snapshot', { status: 'running', lastSequence: 3 }, { eventId: 'evt_newer_snapshot' })).state;
  state = reduceSessionEvent(state, event(2, 'session.status_changed', { status: 'running' })).state;

  expect(state.lastSequence).toBe(2);
  expect(state.status).toBe('running');
});
