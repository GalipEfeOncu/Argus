import { afterEach, expect, test } from 'vitest';
import { useAgentStore } from '@/stores/agentStore';
import { useSessionStore } from '@/stores/sessionStore';
import type { Session } from '@/types/session';
import { createSimulatorScenario } from './helpers/simulatorScenario';

const sessionId = 'session_simulator_test';

function resetStores(): void {
  useAgentStore.getState().clearSession();
  useSessionStore.setState({ sessions: [], activeSessionId: null });
}

afterEach(resetStores);

test('simulator streams canonical deltas and an interrupt closes the active stream through a correlated command', () => {
  const scenario = createSimulatorScenario();
  scenario.simulator.start(sessionId);
  scenario.clock.advanceBy(650);

  const streamingMessage = Object.values(scenario.simulator.getProjection(sessionId)?.messages ?? {}).find((message) => message.streaming);
  expect(streamingMessage).toBeDefined();
  scenario.simulator.interruptActiveParticipant(sessionId);

  const interrupted = scenario.simulator.getProjection(sessionId);
  expect(interrupted?.messages[streamingMessage?.id ?? '']?.streaming).toBe(false);
  expect(interrupted?.events.map((entry) => entry.type)).toEqual(expect.arrayContaining(['message.completed', 'participant.status_changed']));
  expect(Object.keys(interrupted?.pendingCommands ?? {})).toHaveLength(0);
});

test('simulator approval scenario is deterministic and projects canonical events through the shared store path', () => {
  const session: Session = {
    id: sessionId,
    name: 'Simulator test',
    projectPath: 'test-project',
    task: 'Exercise an approval',
    status: 'setup',
    roleConfigs: [],
    messages: [],
    startedAt: 1_700_000_000_000,
    tokenUsage: { inputTokens: 0, outputTokens: 0, totalTokens: 0 },
  };
  useSessionStore.setState({ sessions: [session], activeSessionId: sessionId });
  const scenario = createSimulatorScenario();

  scenario.simulator.start(sessionId);
  scenario.clock.advanceBy(3_300);

  const waitingProjection = scenario.simulator.getProjection(sessionId);
  expect(waitingProjection?.status).toBe('waiting_approval');
  expect(waitingProjection?.lastSequence).toBeGreaterThanOrEqual(11);
  expect(useAgentStore.getState().isInterrupted).toBe(true);
  expect(useAgentStore.getState().messages).toHaveLength(3);
  expect(waitingProjection?.events.map((entry) => entry.type)).toEqual(expect.arrayContaining([
    'assignment.proposed', 'assignment.created', 'assignment.started', 'tool.requested', 'tool.started', 'tool.completed', 'handoff.created', 'artifact.diff_updated', 'usage.updated',
  ]));

  scenario.simulator.resolveApproval(sessionId, true);
  scenario.clock.advanceBy(600);

  expect(scenario.simulator.getProjection(sessionId)?.status).toBe('running');
  expect(useAgentStore.getState().isInterrupted).toBe(false);
  expect(useAgentStore.getState().messages.at(-1)?.content).toContain('isolated workspace');

  scenario.simulator.interruptActiveParticipant(sessionId);
  const interruptedProjection = scenario.simulator.getProjection(sessionId);
  expect(interruptedProjection?.events.at(-1)).toMatchObject({
    type: 'participant.status_changed',
    payload: { participantId: 'coordinator', status: 'stopped' },
  });
  expect(Object.keys(interruptedProjection?.pendingCommands ?? {})).toHaveLength(0);
});
