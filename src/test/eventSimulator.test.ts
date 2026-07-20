import { afterEach, expect, test } from 'vitest';
import { useAgentStore } from '@/stores/agentStore';
import { useSessionStore } from '@/stores/sessionStore';
import type { Session } from '@/types/session';
import { createSimulatorScenario } from './helpers/simulatorScenario';
import { createConfiguration } from '@/services/sessionConfiguration';

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
    configuration: createConfiguration({}),
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

test('simulator honors the configured available-agent pool instead of inventing a fixed pipeline', () => {
  const scenario = createSimulatorScenario();
  const configuration = createConfiguration({}, 'quick');
  scenario.simulator.start(sessionId, configuration);
  scenario.clock.advanceBy(2_600);

  expect(Object.keys(useAgentStore.getState().agents).sort()).toEqual(['builtin-builder', 'coordinator']);
  const actorIds = scenario.simulator.getProjection(sessionId)?.events.map((entry) => entry.actorId) ?? [];
  expect(actorIds).not.toContain('planner');
  expect(actorIds).not.toContain('reviewer');
  expect(actorIds).not.toContain('tester');
  const assignees = scenario.simulator.getProjection(sessionId)?.events.filter((entry) => entry.type === 'assignment.created').map((entry) => entry.payload.assigneeAgentId) ?? [];
  expect(assignees).toEqual(['builtin-builder']);
});

test('a pre-authorized workspace write stays prompt-free and retains the selected instance ID', () => {
  const scenario = createSimulatorScenario();
  const base = createConfiguration({}, 'quick');
  const originalBuilder = base.availableAgents.find((agent) => agent.role === 'builder')!;
  const namedBuilder = { ...originalBuilder, id: 'agent-builder-alpha', label: 'Builder Alpha' };
  const configuration = {
    ...base,
    availableAgents: [...base.availableAgents, namedBuilder],
    availableAgentIds: [namedBuilder.id],
    approvalPolicy: { ...base.approvalPolicy, permissionProfile: 'autonomous' as const, behavior: 'preauthorize_session' as const, preauthorizedCapabilities: ['workspace.write'] },
    preauthorizationScope: '/project',
    preauthorizationAcknowledged: true,
  };
  scenario.simulator.start(sessionId, configuration);
  scenario.clock.advanceBy(3_300);

  const events = scenario.simulator.getProjection(sessionId)?.events ?? [];
  expect(events.map((event) => event.type)).not.toContain('approval.requested');
  expect(events.find((event) => event.type === 'assignment.created')?.payload.assigneeAgentId).toBe('agent-builder-alpha');
});

test('two same-role instances retain distinct legacy-store keys while canonical assignments use an instance ID', () => {
  const scenario = createSimulatorScenario();
  const base = createConfiguration({}, 'quick');
  const builder = base.availableAgents.find((agent) => agent.role === 'builder')!;
  const secondBuilder = { ...builder, id: 'agent-builder-beta', label: 'Builder Beta' };
  scenario.simulator.start(sessionId, { ...base, availableAgents: [...base.availableAgents, secondBuilder], availableAgentIds: [builder.id, secondBuilder.id] });
  scenario.clock.advanceBy(550);

  expect(Object.keys(useAgentStore.getState().agents).sort()).toEqual(['agent-builder-beta', 'builtin-builder', 'coordinator']);
  expect(scenario.simulator.getProjection(sessionId)?.events.find((event) => event.type === 'assignment.created')?.payload.assigneeAgentId).toBe('builtin-builder');
});

test('simulator rejects invalid pre-authorization when invoked outside the setup UI', () => {
  const scenario = createSimulatorScenario();
  const base = createConfiguration({}, 'quick');
  const unsafe = {
    ...base,
    approvalPolicy: { ...base.approvalPolicy, permissionProfile: 'autonomous' as const, behavior: 'preauthorize_session' as const, preauthorizedCapabilities: ['workspace.write'] },
  };
  expect(() => scenario.simulator.start(sessionId, unsafe)).toThrow('Simulator configuration is invalid');
});
