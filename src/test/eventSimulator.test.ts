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
  expect(waitingProjection?.lastSequence).toBe(11);
  expect(useAgentStore.getState().isInterrupted).toBe(true);
  expect(useAgentStore.getState().messages.map((message) => message.id)).toEqual([
    'sim_3',
    'sim_7',
    'sim_11',
  ]);

  scenario.simulator.resolveApproval(sessionId, true);
  scenario.clock.advanceBy(600);

  expect(scenario.simulator.getProjection(sessionId)?.status).toBe('running');
  expect(useAgentStore.getState().isInterrupted).toBe(false);
  expect(useAgentStore.getState().messages.at(-1)?.content).toContain('isolated workspace');
});
