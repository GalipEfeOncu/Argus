import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { RuntimeContext } from '@/components/workflow/RuntimeContext';
import { ApprovalBar } from '@/components/chat/ApprovalBar';
import { SessionControls } from '@/components/chat/SessionControls';
import { createSessionProjection, reduceSessionEvent } from '@/services/sessionProjection';
import { useSessionRoomStore } from '@/stores/sessionRoomStore';
import { useSessionStore } from '@/stores/sessionStore';
import { createConfiguration } from '@/services/sessionConfiguration';
import type { ArgusSessionEvent } from '@/types/events';

const sendInterrupt = vi.fn();
const controlSession = vi.fn();
const updateConfiguration = vi.fn();
const resolveDecision = vi.fn();
const sendApproval = vi.fn();

vi.mock('@/hooks/useWebSocket', () => ({ useWebSocket: () => ({ sendInterrupt, controlSession, updateConfiguration, resolveDecision, sendApproval }) }));

const sessionId = 'ses_runtime';

function event<T extends ArgusSessionEvent['type']>(sequence: number, type: T, payload: Extract<ArgusSessionEvent, { type: T }>['payload']): Extract<ArgusSessionEvent, { type: T }> {
  return { version: 1, eventId: `evt-${sequence}`, sessionId, sequence, timestamp: '2026-07-20T12:00:00Z', actorId: 'system', type, payload } as Extract<ArgusSessionEvent, { type: T }>;
}

beforeEach(() => {
  vi.clearAllMocks();
  let state = reduceSessionEvent(createSessionProjection(sessionId), event(0, 'session.snapshot', { status: 'running', lastSequence: 0 })).state;
  [
    event(1, 'participant.status_changed', { participantId: 'builder-a', participantKind: 'agent', status: 'working', actionSummary: 'Writing the change' }),
    event(2, 'participant.status_changed', { participantId: 'reviewer-a', participantKind: 'agent', status: 'waiting' }),
    event(3, 'participant.status_changed', { participantId: 'tester-a', participantKind: 'agent', status: 'stopped' }),
    event(4, 'assignment.created', { assignmentId: 'assignment-a', proposalId: 'proposal-a', assigneeAgentId: 'builder-a', configurationVersion: 1, policyHash: 'policy', operationClass: 'mutating' }),
    event(5, 'gate.status_changed', { gateId: 'gate-review', role: 'reviewer', status: 'pending' }),
    event(6, 'limit.warning', { counter: 'tool_calls', scopeId: 'assignment-a', current: 8, threshold: 10, hard: false, resolution: 'ask_user' }),
    event(7, 'approval.requested', { approvalId: 'approval-a', capability: 'workspace.write', scopeSummary: 'isolated workspace' }),
    event(8, 'decision.requested', { decisionId: 'decision-a', scopeId: 'assignment-a', choices: ['reassign', 'deliver_partial'], reasonSummary: 'A hard limit needs a decision.' }),
  ].forEach((next) => { state = reduceSessionEvent(state, next).state; });
  useSessionRoomStore.setState({ projections: { [sessionId]: state } });
  useSessionStore.setState({ sessions: [{ id: sessionId, name: 'Runtime', projectPath: '/project', task: 'Runtime test', status: 'running', roleConfigs: [], configuration: createConfiguration({}), messages: [], startedAt: 0, tokenUsage: { inputTokens: 0, outputTokens: 0, totalTokens: 0 } }], activeSessionId: sessionId });
});

afterEach(cleanup);

test('context panel groups participants and exposes visible, keyboard-operable runtime controls', () => {
  render(<RuntimeContext sessionId={sessionId} />);
  expect(screen.getByText('Active (1)')).toBeInTheDocument();
  expect(screen.getByText('Waiting (1)')).toBeInTheDocument();
  expect(screen.getByText('Done (1)')).toBeInTheDocument();
  expect(screen.getByText('Current writer')).toBeInTheDocument();
  expect(screen.getAllByText('builder-a')).toHaveLength(2);
  expect(screen.getByText(/reviewer: pending/)).toBeInTheDocument();
  expect(screen.getByText(/tool_calls: 92 remaining of 100/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  fireEvent.click(screen.getByRole('button', { name: 'Request consequence preview' }));
  fireEvent.click(screen.getByRole('button', { name: 'Interrupt' }));
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
  fireEvent.click(screen.getByRole('button', { name: 'deliver partial' }));
  expect(controlSession).toHaveBeenCalledWith('pause');
  expect(controlSession).toHaveBeenCalledWith('cancel');
  expect(updateConfiguration).toHaveBeenCalledWith(1, expect.objectContaining({ limitResolution: 'ask_user' }));
  expect(sendInterrupt).toHaveBeenCalledWith('builder-a');
  expect(sendApproval).toHaveBeenCalledWith(true, 'approval-a');
  expect(resolveDecision).toHaveBeenCalledWith('decision-a', 'deliver_partial');
});

test('approval bar sends the projected approval ID and stays visible while its command is pending', () => {
  render(<ApprovalBar sessionId={sessionId} />);
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
  expect(sendApproval).toHaveBeenCalledWith(true, 'approval-a');

  const current = useSessionRoomStore.getState().projections[sessionId]!;
  act(() => useSessionRoomStore.setState({ projections: { [sessionId]: { ...current, pendingCommands: { cmd: { command: { commandId: 'cmd', type: 'approval.resolve', payload: { approvalId: 'approval-a', resolution: 'approve' } }, attempts: 1 } } } } }));
  expect(screen.getByText(/Decision pending/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();
});

test('session-header controls remain available outside the context panel and block duplicate commands', () => {
  render(<SessionControls sessionId={sessionId} />);
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(controlSession).toHaveBeenCalledWith('pause');
  expect(controlSession).toHaveBeenCalledWith('cancel');
});

test('accepted runtime configuration patches become the next durable client-side configuration snapshot', () => {
  useSessionStore.getState().patchSessionConfiguration(sessionId, {
    availableAgentIds: ['builtin-builder'],
    requiredRoleRules: [{ id: 'gate-builder', role: 'builder', applicability: 'always', successEvidence: 'verified_change', minimumCompletions: 1 }],
    approvalBehavior: 'deny_interactive',
    limitResolution: 'stop',
  });
  const configuration = useSessionStore.getState().sessions[0].configuration;
  expect(configuration.availableAgentIds).toEqual(['builtin-builder']);
  expect(configuration.requiredRoleRules).toMatchObject([{ id: 'gate-builder', role: 'builder' }]);
  expect(configuration.approvalPolicy).toMatchObject({ behavior: 'deny_interactive', limitResolution: 'stop' });
});
