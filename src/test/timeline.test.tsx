import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ArgusSessionEvent } from '@/types/events';
import { MessageInput, extractMentions } from '@/components/chat/MessageInput';
import { MessageList } from '@/components/chat/MessageList';
import { LiveTimelineAnnouncer } from '@/components/chat/LiveTimelineAnnouncer';
import { createSessionProjection, reduceSessionEvent, type SessionProjection } from '@/services/sessionProjection';
import { createTimelineEntries } from '@/services/timelineModel';
import { useSessionRoomStore } from '@/stores/sessionRoomStore';
import { useSessionStore } from '@/stores/sessionStore';

const sendMessage = vi.fn();
const sendInterrupt = vi.fn();

vi.mock('@/hooks/useWebSocket', () => ({
  useWebSocket: () => ({ sendMessage, sendInterrupt, sendApproval: vi.fn() }),
}));

const sessionId = 'ses_timeline';

function event<T extends ArgusSessionEvent['type']>(
  sequence: number,
  type: T,
  payload: Extract<ArgusSessionEvent, { type: T }>['payload'],
  actorId = 'system',
): Extract<ArgusSessionEvent, { type: T }> {
  return {
    version: 1, eventId: `evt_${sequence}_${type}`, sessionId, sequence,
    timestamp: '2026-07-19T12:00:00Z', actorId, type, payload,
  } as Extract<ArgusSessionEvent, { type: T }>;
}

function projection(events: ArgusSessionEvent[]): SessionProjection {
  return events.reduce((state, next) => reduceSessionEvent(state, next).state, createSessionProjection(sessionId));
}

function snapshot(): ArgusSessionEvent {
  return event(0, 'session.snapshot', { status: 'running', lastSequence: 0 });
}

beforeEach(() => {
  sendMessage.mockReset();
  sendInterrupt.mockReset();
  useSessionStore.setState({ activeSessionId: sessionId });
  useSessionRoomStore.setState({ projections: {}, streamingRenderCommits: 0 });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

test('composer sends with keyboard, visibly defaults to Coordinator, and parses explicit mentions', () => {
  render(<MessageInput sessionId={sessionId} />);
  const input = screen.getByLabelText('Message for shared room');
  expect(screen.getByText('Targets: Coordinator')).toBeInTheDocument();
  fireEvent.change(input, { target: { value: '@builder inspect this' } });
  expect(screen.getByText('Targets: builder')).toBeInTheDocument();
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(sendMessage).toHaveBeenCalledWith('@builder inspect this', ['builder']);
  expect(extractMentions('@Builder @builder @tester')).toEqual(['builder', 'tester']);
});

test('Escape requests an interruption while a message is streaming', () => {
  const state = projection([
    snapshot(),
    event(1, 'message.created', { messageId: 'msg_stream', authorId: 'coordinator', authorKind: 'coordinator', content: 'Planning', streaming: true }, 'coordinator'),
  ]);
  useSessionRoomStore.setState({ projections: { [sessionId]: state } });
  render(<MessageInput sessionId={sessionId} />);
  fireEvent.keyDown(screen.getByLabelText('Message for shared room'), { key: 'Escape' });
  expect(sendInterrupt).toHaveBeenCalledTimes(1);
});

test('collapsed specialist detail remains in the ordered room and can be inspected', () => {
  const state = projection([
    snapshot(),
    event(1, 'message.created', { messageId: 'msg_specialist', authorId: 'builder', authorKind: 'agent', content: 'I found the smallest safe change.' }, 'builder'),
  ]);
  useSessionRoomStore.setState({ projections: { [sessionId]: state } });
  render(<MessageList sessionId={sessionId} />);
  fireEvent.click(screen.getByRole('button', { name: 'Collapse specialist detail' }));
  expect(screen.getByRole('button', { name: /Specialist detail collapsed/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Specialist detail collapsed/ }));
  expect(screen.getByText('I found the smallest safe change.')).toBeInTheDocument();
});

test('timeline correlation links preserve stable event IDs and focus the linked event', () => {
  const state = projection([
    snapshot(),
    event(1, 'assignment.created', { assignmentId: 'assign_1', proposalId: 'proposal_1', assigneeAgentId: 'builder', configurationVersion: 1, policyHash: 'hash', operationClass: 'mutating' }, 'coordinator'),
    event(2, 'tool.requested', { toolExecutionId: 'tool_1', assignmentId: 'assign_1', toolName: 'read_file', operationClass: 'read_only', requestSummary: 'Read the relevant source.' }, 'builder'),
  ]);
  useSessionRoomStore.setState({ projections: { [sessionId]: state } });
  render(<MessageList sessionId={sessionId} />);
  const link = screen.getByRole('button', { name: 'evt_1_assignment.created' });
  fireEvent.click(link);
  expect(document.activeElement?.id).toBe('event-evt_1_assignment.created');
});

test('assignment evidence remains visible and correlates to its artifact', () => {
  const state = projection([
    snapshot(),
    event(1, 'artifact.diff_updated', { artifactId: 'artifact_1', filePath: 'src/example.ts', additions: 2, deletions: 1, byteLength: 20 }),
    event(2, 'assignment.completed', { assignmentId: 'assignment_1', status: 'completed', outputSummary: 'Implemented the requested change.', evidence: [{ kind: 'passing_test_run', summary: 'Tests passed.', artifactIds: ['artifact_1'] }] }),
  ]);
  const complete = createTimelineEntries(state).find((entry) => entry.event.type === 'assignment.completed');
  expect(complete?.summary).toContain('Evidence (passing_test_run): Tests passed.');
  expect(complete?.relatedEventIds).toContain('evt_1_artifact.diff_updated');
});

test('shows an unread affordance instead of forcing a scrolled-away user to the latest event', () => {
  const initial = projection([snapshot(), event(1, 'session.status_changed', { status: 'running' })]);
  useSessionRoomStore.setState({ projections: { [sessionId]: initial } });
  render(<MessageList sessionId={sessionId} />);
  const viewport = screen.getByRole('log');
  Object.defineProperties(viewport, {
    scrollHeight: { configurable: true, value: 2_000 },
    clientHeight: { configurable: true, value: 300 },
    scrollTop: { configurable: true, value: 0 },
  });
  fireEvent.scroll(viewport);
  const later = projection([snapshot(), event(1, 'session.status_changed', { status: 'running' }), event(2, 'session.status_changed', { status: 'paused' })]);
  act(() => useSessionRoomStore.setState({ projections: { [sessionId]: later } }));
  expect(screen.getByRole('button', { name: /1 new event/ })).toBeInTheDocument();
});

test('timeline renders a bounded DOM window for 10,000 events', () => {
  const events: ArgusSessionEvent[] = [];
  for (let sequence = 1; sequence <= 10_000; sequence += 1) {
    events.push(event(sequence, 'session.status_changed', { status: 'running' }));
  }
  const state = { ...createSessionProjection(sessionId), events, lastSequence: 10_000, status: 'running' };
  useSessionRoomStore.setState({ projections: { [sessionId]: state } });
  render(<MessageList sessionId={sessionId} />);
  expect(screen.getByText('10,000 ordered events')).toBeInTheDocument();
  expect(document.querySelectorAll('[data-event-id]').length).toBeLessThanOrEqual(20);
  const viewport = screen.getByRole('log');
  Object.defineProperty(viewport, 'scrollTop', { configurable: true, value: 9_000 * 92 });
  fireEvent.scroll(viewport);
  expect(document.querySelectorAll('[data-event-id]').length).toBeLessThanOrEqual(20);
  expect(document.getElementById('event-evt_9000_session.status_changed')).toBeInTheDocument();
});

test('live announcements throttle updates and never narrate streaming deltas', () => {
  vi.useFakeTimers();
  const message = event(1, 'message.created', { messageId: 'message_1', authorId: 'coordinator', authorKind: 'coordinator', content: 'First message' }, 'coordinator');
  const first = createTimelineEntries(projection([snapshot(), message])).at(-1);
  const delta = createTimelineEntries(projection([snapshot(), message, event(2, 'message.delta', { messageId: 'message_1', delta: ' more' }, 'coordinator')])).at(-1);
  const view = render(<LiveTimelineAnnouncer latestEntry={first} />);
  view.rerender(<LiveTimelineAnnouncer latestEntry={delta} />);
  act(() => vi.advanceTimersByTime(900));
  expect(screen.getByText(/Streaming update: First message more/)).toBeInTheDocument();
});

describe('projection render batching', () => {
  test('coalesces streaming paints and flushes the latest projection once', () => {
    const first = projection([snapshot()]);
    const second = projection([snapshot(), event(1, 'message.created', { messageId: 'm', authorId: 'coordinator', authorKind: 'coordinator', content: 'A', streaming: true }, 'coordinator'), event(2, 'message.delta', { messageId: 'm', delta: 'B' }, 'coordinator')]);
    const store = useSessionRoomStore.getState();
    store.publishProjection(sessionId, first, true);
    store.publishProjection(sessionId, second, true);
    store.flushStreamingProjection(sessionId);
    expect(useSessionRoomStore.getState().projections[sessionId]?.messages.m.content).toBe('AB');
    expect(useSessionRoomStore.getState().streamingRenderCommits).toBe(1);
  });

  test('holds streaming paints while a background frame is suspended and flushes on return', () => {
    vi.useFakeTimers();
    const state = projection([snapshot()]);
    const originalVisibility = Object.getOwnPropertyDescriptor(document, 'visibilityState');
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    useSessionRoomStore.getState().publishProjection(sessionId, state, true);
    act(() => vi.advanceTimersByTime(20));
    expect(useSessionRoomStore.getState().streamingRenderCommits).toBe(0);
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(useSessionRoomStore.getState().streamingRenderCommits).toBe(1);
    if (originalVisibility !== undefined) Object.defineProperty(document, 'visibilityState', originalVisibility);
  });
});
