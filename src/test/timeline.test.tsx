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
import { useAgentStore } from '@/stores/agentStore';

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

function connectedProjection(events: ArgusSessionEvent[] = [snapshot()]): SessionProjection {
  return { ...projection(events), connection: 'connected' };
}

beforeEach(() => {
  sendMessage.mockReset();
  sendMessage.mockReturnValue({ status: 'pending', commandId: 'cmd_message' });
  sendInterrupt.mockReset();
  useSessionStore.setState({ activeSessionId: sessionId });
  useSessionRoomStore.setState({ projections: {}, streamingRenderCommits: 0 });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

test('composer sends with keyboard, visibly defaults to Coordinator, and parses explicit mentions', () => {
  useSessionRoomStore.setState({ projections: { [sessionId]: connectedProjection() } });
  render(<MessageInput sessionId={sessionId} />);
  const input = screen.getByLabelText('Message for shared room');
  expect(screen.getByText('Targets: Coordinator')).toBeInTheDocument();
  fireEvent.change(input, { target: { value: '@builder inspect this' } });
  expect(screen.getByText('Targets: builder')).toBeInTheDocument();
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(sendMessage).toHaveBeenCalledWith('@builder inspect this', ['builder']);
  expect(extractMentions('@Builder @builder @tester')).toEqual(['builder', 'tester']);
});

test('waiting for approval keeps Coordinator messaging available without resolving the approval', () => {
  const waiting = connectedProjection([
    snapshot(),
    event(1, 'session.status_changed', { status: 'waiting_approval' }),
    event(2, 'approval.requested', { approvalId: 'approval_1', capability: 'workspace.write', scopeSummary: 'Session workspace only.' }),
  ]);
  useSessionRoomStore.setState({ projections: { [sessionId]: waiting } });
  useAgentStore.setState({ isInterrupted: true, interruptReason: 'Waiting for approval' });
  render(<MessageInput sessionId={sessionId} />);

  const input = screen.getByLabelText('Message for shared room');
  fireEvent.change(input, { target: { value: 'Coordinator, use the narrower approach.' } });
  expect(input).toBeEnabled();
  expect(screen.getByText(/not approve or reject/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Execute Task' }));
  expect(sendMessage).toHaveBeenCalledWith('Coordinator, use the narrower approach.', []);
});

test.each(['reconnecting', 'resyncing'] as const)('%s and unavailable dispatch preserve an editable draft', (connection) => {
  useSessionRoomStore.setState({ projections: { [sessionId]: { ...connectedProjection(), connection } } });
  render(<MessageInput sessionId={sessionId} />);
  const input = screen.getByLabelText('Message for shared room');
  fireEvent.change(input, { target: { value: 'Keep this draft' } });

  expect(input).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Execute Task' })).toBeDisabled();
  expect(screen.getByText(/Keep editing/)).toBeInTheDocument();

  act(() => useSessionRoomStore.setState({ projections: { [sessionId]: connectedProjection() } }));
  sendMessage.mockReturnValueOnce({ status: 'unavailable' });
  fireEvent.click(screen.getByRole('button', { name: 'Execute Task' }));
  expect(input).toHaveValue('Keep this draft');
  expect(screen.getByRole('alert')).toHaveTextContent('not sent');
});

test('canonical message confirmation clears an unchanged submitted draft', () => {
  useSessionRoomStore.setState({ projections: { [sessionId]: connectedProjection() } });
  render(<MessageInput sessionId={sessionId} />);
  const input = screen.getByLabelText('Message for shared room');
  fireEvent.change(input, { target: { value: 'Confirmed draft' } });
  fireEvent.click(screen.getByRole('button', { name: 'Execute Task' }));

  const confirmed = {
    ...event(1, 'message.created', { messageId: 'msg_confirmed', authorId: 'human', authorKind: 'human', content: 'Confirmed draft' }, 'human'),
    correlationId: 'cmd_message',
  } as ArgusSessionEvent;
  act(() => useSessionRoomStore.setState({ projections: { [sessionId]: connectedProjection([snapshot(), confirmed]) } }));
  expect(input).toHaveValue('');
  expect(screen.queryByText(/Message pending/)).not.toBeInTheDocument();
});

test('canonical message confirmation clears only the submitted draft and a correlated error preserves it', () => {
  useSessionRoomStore.setState({ projections: { [sessionId]: connectedProjection() } });
  const { unmount } = render(<MessageInput sessionId={sessionId} />);
  const input = screen.getByLabelText('Message for shared room');
  fireEvent.change(input, { target: { value: 'First draft' } });
  fireEvent.click(screen.getByRole('button', { name: 'Execute Task' }));
  expect(input).toHaveValue('First draft');
  expect(screen.getByText(/Message pending/)).toBeInTheDocument();

  fireEvent.change(input, { target: { value: 'Next draft' } });
  const confirmed = {
    ...event(1, 'message.created', { messageId: 'msg_human', authorId: 'human', authorKind: 'human', content: 'First draft' }, 'human'),
    correlationId: 'cmd_message',
  } as ArgusSessionEvent;
  act(() => useSessionRoomStore.setState({ projections: { [sessionId]: connectedProjection([snapshot(), confirmed]) } }));
  expect(input).toHaveValue('Next draft');

  unmount();
  sendMessage.mockReturnValueOnce({ status: 'pending', commandId: 'cmd_rejected' });
  useSessionRoomStore.setState({ projections: { [sessionId]: connectedProjection() } });
  render(<MessageInput sessionId={sessionId} />);
  const rejectedInput = screen.getByLabelText('Message for shared room');
  fireEvent.change(rejectedInput, { target: { value: 'Retry this message' } });
  fireEvent.click(screen.getByRole('button', { name: 'Execute Task' }));
  const rejected = {
    ...event(1, 'error.created', { errorId: 'err_message', code: 'command_rejected', summary: 'Message could not be accepted.', recoverable: true }),
    correlationId: 'cmd_rejected',
  } as ArgusSessionEvent;
  act(() => useSessionRoomStore.setState({ projections: { [sessionId]: connectedProjection([snapshot(), rejected]) } }));
  expect(rejectedInput).toHaveValue('Retry this message');
  expect(screen.getByRole('alert')).toHaveTextContent('Message could not be accepted.');
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

test('direct chat presents one message card while retaining streaming events in the projection', () => {
  const state = projection([
    snapshot(),
    event(1, 'message.created', { messageId: 'msg_human', authorId: 'human', authorKind: 'human', content: 'Hi' }, 'human'),
    event(2, 'message.created', { messageId: 'msg_reply', authorId: 'coordinator', authorKind: 'coordinator', content: 'Hi', streaming: true }, 'coordinator'),
    event(3, 'message.delta', { messageId: 'msg_reply', delta: '! How can I help you?' }, 'coordinator'),
    event(4, 'message.completed', { messageId: 'msg_reply' }, 'coordinator'),
    event(5, 'usage.updated', { scopeId: 'chat_1', inputTokens: 2, outputTokens: 6, normalizedCost: null, costUncertainty: 'unavailable', durationMs: 0 }),
  ]);
  useSessionRoomStore.setState({ projections: { [sessionId]: state } });

  render(<MessageList sessionId={sessionId} sessionKind="chat" />);

  expect(screen.getByText('2 messages')).toBeInTheDocument();
  expect(screen.getByText('Hi! How can I help you?')).toBeInTheDocument();
  expect(screen.queryByText('Streaming update')).not.toBeInTheDocument();
  expect(screen.queryByText('Usage updated')).not.toBeInTheDocument();
  expect(state.events.map((entry) => entry.type)).toEqual([
    'message.created', 'message.created', 'message.delta', 'message.completed', 'usage.updated',
  ]);
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
