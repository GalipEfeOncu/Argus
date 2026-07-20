import type { AgentInfo, AgentRole, ModelRef } from '@/types/agent';
import type { ArgusSessionCommand, ArgusSessionEvent } from '@/types/events';
import { useAgentStore } from '@/stores/agentStore';
import { InMemorySessionTransport, SessionStreamClient } from './sessionTransport';
import type { ProjectedParticipant, SessionProjection } from './sessionProjection';
import { syncLegacyProjection } from './legacyProjectionBridge';
import { useSessionRoomStore } from '@/stores/sessionRoomStore';
import type { AgentInstance, SessionConfiguration } from '@/types/session';
import { validateConfiguration } from './sessionConfiguration';

const demoModel: ModelRef = {
  providerId: 'demo',
  modelId: 'argus-simulator',
  displayName: 'Argus Simulator',
};

const demoRoles: AgentRole[] = ['coordinator', 'planner', 'builder', 'reviewer', 'tester', 'ui_agent'];
type SimulatorTimer = ReturnType<typeof setTimeout>;
interface SimulatorAgent { id: string; role: AgentRole; }
const coordinator: SimulatorAgent = { id: 'coordinator', role: 'coordinator' };

export interface SimulatorClock {
  now(): number;
  setTimeout(callback: () => void, delayMs: number): SimulatorTimer;
  clearTimeout(timer: SimulatorTimer): void;
}

export interface EventSimulatorDependencies {
  clock: SimulatorClock;
  createId(): string;
}

const browserSimulatorDependencies: EventSimulatorDependencies = {
  clock: {
    now: () => Date.now(),
    setTimeout: (callback, delayMs) => setTimeout(callback, delayMs),
    clearTimeout: (timer) => clearTimeout(timer),
  },
  createId: () => crypto.randomUUID(),
};

/**
 * The simulator produces canonical wire events and sends them through the same
 * SessionStreamClient that consumes live WebSocket events.
 */
export class EventSimulator {
  private readonly timers = new Map<string, SimulatorTimer[]>();
  private readonly sequences = new Map<string, number>();
  private readonly transports = new Map<string, InMemorySessionTransport>();
  private readonly clients = new Map<string, SessionStreamClient>();
  private readonly unsubscribeProjection = new Map<string, () => void>();
  private readonly streamingMessages = new Map<string, string>();
  private readonly sessionAgents = new Map<string, SimulatorAgent[]>();

  constructor(private readonly dependencies: EventSimulatorDependencies = browserSimulatorDependencies) {}

  isActive(sessionId: string): boolean {
    return this.clients.has(sessionId);
  }

  getProjection(sessionId: string): SessionProjection | undefined {
    return this.clients.get(sessionId)?.getProjection();
  }

  start(sessionId: string, configuration?: SessionConfiguration): void {
    if (this.isActive(sessionId)) return;
    if (configuration !== undefined) {
      const errors = validateConfiguration(configuration);
      if (errors.length > 0) throw new Error(`Simulator configuration is invalid: ${errors.join(' ')}`);
    }

    const transport = new InMemorySessionTransport();
    const client = new SessionStreamClient(transport, sessionId, this.dependencies.clock);
    const selectedAgents: SimulatorAgent[] = configuration === undefined
      ? demoRoles.map((role) => ({ id: role, role }))
      : [coordinator, ...configuration.availableAgents.filter((agent) => configuration.availableAgentIds.includes(agent.id)).map(toSimulatorAgent)];
    const agents: AgentInfo[] = selectedAgents.map((agent) => ({
      instanceId: agent.id,
      label: configuration?.availableAgents.find((candidate) => candidate.id === agent.id)?.label ?? (agent.role === 'coordinator' ? 'Coordinator' : agent.role),
      role: agent.role,
      status: 'idle',
      modelRef: demoModel,
      tokenCount: 0,
    }));
    useAgentStore.getState().initAgents(agents);
    this.transports.set(sessionId, transport);
    this.clients.set(sessionId, client);
    this.sequences.set(sessionId, 0);
    this.timers.set(sessionId, []);
    this.sessionAgents.set(sessionId, selectedAgents);
    this.unsubscribeProjection.set(sessionId, client.subscribe((projection, update) => {
      useSessionRoomStore.getState().publishProjection(sessionId, projection, update.isStreamingUpdate);
      syncLegacyProjection(sessionId, projection);
    }));
    client.connect();

    this.snapshot(sessionId, 'running');
    this.schedule(sessionId, 350, () => this.participant(sessionId, coordinator, 'working', 'Reviewing the task and available team capabilities'));
    const planningAgent = this.agentFor(sessionId, 'planner');
    const implementationAgent = this.agentFor(sessionId, 'builder', planningAgent);
    this.schedule(sessionId, 450, () => this.emit(sessionId, 'assignment.proposed', coordinator.id, {
      proposalId: 'demo-proposal', assigneeAgentId: planningAgent.id, objective: 'Map the project and propose the smallest safe change.',
      acceptanceCriteria: ['Identify affected files', 'Hand off an implementation plan'], operationClass: 'read_only', reasonSummary: 'Start with a bounded visible plan.',
    }));
    this.schedule(sessionId, 500, () => this.emit(sessionId, 'assignment.created', coordinator.id, {
      assignmentId: 'demo-assignment', proposalId: 'demo-proposal', assigneeAgentId: planningAgent.id, configurationVersion: 1, policyHash: 'demo-policy', operationClass: 'read_only',
    }));
    this.schedule(sessionId, 550, () => this.emit(sessionId, 'assignment.started', planningAgent.id, { assignmentId: 'demo-assignment', assigneeAgentId: planningAgent.id }));
    this.schedule(sessionId, 650, () => this.streamMessage(
      sessionId,
      coordinator,
      'I will coordinate this session in the open.',
      [' I’m assigning planning first,', ' then I’ll request implementation and review.'],
    ));
    this.schedule(sessionId, 1200, () => this.participant(sessionId, planningAgent, 'working', 'Mapping the project and acceptance criteria'));
    this.schedule(sessionId, 1600, () => this.message(sessionId, planningAgent, 'I will inspect the relevant project files, identify the smallest safe change, and hand the implementation plan to the next available specialist.'));
    this.schedule(sessionId, 2200, () => this.participant(sessionId, implementationAgent, 'working', 'Reading project context'));
    this.schedule(sessionId, 2500, () => this.tool(sessionId, implementationAgent, planningAgent));
    const writePreauthorized = configuration?.approvalPolicy.behavior === 'preauthorize_session'
      && configuration.approvalPolicy.preauthorizedCapabilities.includes('workspace.write');
    this.schedule(sessionId, 3300, () => writePreauthorized
      ? this.message(sessionId, implementationAgent, 'The pre-authorized workspace change completed within the selected session scope.')
      : this.approval(sessionId, implementationAgent));
  }

  stop(sessionId: string): void {
    (this.timers.get(sessionId) ?? []).forEach((timer) => this.dependencies.clock.clearTimeout(timer));
    this.unsubscribeProjection.get(sessionId)?.();
    this.clients.get(sessionId)?.disconnect();
    this.unsubscribeProjection.delete(sessionId);
    this.clients.delete(sessionId);
    this.transports.delete(sessionId);
    this.timers.delete(sessionId);
    this.sequences.delete(sessionId);
    this.streamingMessages.delete(sessionId);
    this.sessionAgents.delete(sessionId);
    useSessionRoomStore.getState().clearProjection(sessionId);
  }

  sendHumanMessage(sessionId: string, content: string, mentionIds: string[] = []): void {
    const client = this.clients.get(sessionId);
    if (client === undefined) return;
    const commandId = this.dependencies.createId();
    client.send({ commandId, type: 'message.send', payload: { content, ...(mentionIds.length === 0 ? {} : { mentionIds }) } });
    this.emit(sessionId, 'message.created', 'human', {
      messageId: this.dependencies.createId(), authorId: 'human', authorKind: 'human', content, ...(mentionIds.length === 0 ? {} : { mentionIds }),
    }, commandId);
    this.schedule(sessionId, 300, () => this.message(sessionId, coordinator, 'Acknowledged. I added your instruction to the active assignment and will keep it visible to the team.'));
  }

  resolveApproval(sessionId: string, approved: boolean): void {
    const client = this.clients.get(sessionId);
    if (client === undefined) return;
    const commandId = this.dependencies.createId();
    const command: ArgusSessionCommand = approved
      ? { commandId, type: 'approval.resolve', payload: { approvalId: 'demo-approval', resolution: 'approve' } }
      : { commandId, type: 'approval.resolve', payload: { approvalId: 'demo-approval', resolution: 'reject' } };
    client.send(command);
    this.emit(sessionId, 'approval.resolved', 'human', {
      approvalId: 'demo-approval', resolution: approved ? 'approved' : 'rejected',
      reasonSummary: approved ? 'User approved the requested workspace action.' : 'User rejected the requested workspace action.',
    }, commandId);
    this.emit(sessionId, 'session.status_changed', 'system', { status: 'running' });
    const implementationAgent = this.agentFor(sessionId, 'builder');
    this.participant(sessionId, implementationAgent, 'working', approved ? 'Applying an isolated workspace change' : 'Replanning after user feedback');
    this.schedule(sessionId, 600, () => this.message(sessionId, implementationAgent, approved ? 'The change was applied in the isolated workspace. I am preparing a diff for review.' : 'I will revise the approach before making a workspace change.'));
  }

  interruptActiveParticipant(sessionId: string): void {
    const client = this.clients.get(sessionId);
    if (client === undefined) return;
    const commandId = this.dependencies.createId();
    client.send({
      commandId,
      type: 'participant.interrupt',
      payload: { participantId: 'coordinator', reasonSummary: 'Interrupted by the user.' },
    });
    const streamingMessageId = this.streamingMessages.get(sessionId);
    if (streamingMessageId !== undefined) {
      this.emit(sessionId, 'message.completed', 'human', { messageId: streamingMessageId }, commandId);
      this.streamingMessages.delete(sessionId);
    }
    this.emit(sessionId, 'participant.status_changed', 'human', {
      participantId: 'coordinator', participantKind: 'coordinator', status: 'stopped', actionSummary: 'Interrupted by the user.',
    }, commandId);
  }

  private snapshot(sessionId: string, status: 'running' | 'waiting_approval'): void {
    this.transport(sessionId).emit({
      version: 1,
      eventId: this.dependencies.createId(),
      sessionId,
      sequence: 0,
      timestamp: new Date(this.dependencies.clock.now()).toISOString(),
      type: 'session.snapshot',
      actorId: 'system',
      payload: { status, lastSequence: 0 },
    });
  }

  private schedule(sessionId: string, delay: number, action: () => void): void {
    const timer = this.dependencies.clock.setTimeout(action, delay);
    this.timers.get(sessionId)?.push(timer);
  }

  private emit(sessionId: string, type: ArgusSessionEvent['type'], actorId: string, payload: Record<string, unknown>, correlationId?: string): void {
    const sequence = (this.sequences.get(sessionId) ?? 0) + 1;
    this.sequences.set(sessionId, sequence);
    const event = {
      version: 1,
      eventId: this.dependencies.createId(),
      sessionId,
      sequence,
      timestamp: new Date(this.dependencies.clock.now()).toISOString(),
      type,
      actorId,
      ...(correlationId === undefined ? {} : { correlationId }),
      payload,
    } as unknown as ArgusSessionEvent;
    this.transport(sessionId).emit(event);
  }

  private participant(sessionId: string, agent: SimulatorAgent, status: ProjectedParticipant['status'], actionSummary: string): void {
    this.emit(sessionId, 'participant.status_changed', agent.id, {
      participantId: agent.id, participantKind: agent.role === 'coordinator' ? 'coordinator' : 'agent', status, actionSummary,
    });
  }

  private message(sessionId: string, author: SimulatorAgent, content: string): void {
    this.emit(sessionId, 'message.created', author.id, {
      messageId: this.dependencies.createId(), authorId: author.id, authorKind: author.role === 'coordinator' ? 'coordinator' : 'agent', content,
    });
    this.participant(sessionId, author, 'stopped', 'Shared an update');
  }

  private streamMessage(sessionId: string, author: SimulatorAgent, initialContent: string, deltas: string[]): void {
    const messageId = this.dependencies.createId();
    this.streamingMessages.set(sessionId, messageId);
    this.emit(sessionId, 'message.created', author.id, {
      messageId, authorId: author.id, authorKind: author.role === 'coordinator' ? 'coordinator' : 'agent', content: initialContent, streaming: true,
    });
    deltas.forEach((delta, index) => this.schedule(sessionId, (index + 1) * 90, () => {
      if (this.streamingMessages.get(sessionId) !== messageId) return;
      this.emit(sessionId, 'message.delta', author.id, { messageId, delta });
      if (index === deltas.length - 1) {
        this.emit(sessionId, 'message.completed', author.id, { messageId });
        this.streamingMessages.delete(sessionId);
      }
    }));
  }

  private tool(sessionId: string, implementationAgent: SimulatorAgent, planningAgent: SimulatorAgent): void {
    this.emit(sessionId, 'message.created', implementationAgent.id, {
      messageId: this.dependencies.createId(), authorId: implementationAgent.id, authorKind: 'agent', content: 'I am reading the current project context before proposing a change.',
    });
    this.emit(sessionId, 'tool.requested', implementationAgent.id, {
      toolExecutionId: 'demo-read-project', assignmentId: 'demo-assignment', toolName: 'read_file', operationClass: 'read_only', requestSummary: 'Read the current project context.',
    });
    this.emit(sessionId, 'tool.started', implementationAgent.id, { toolExecutionId: 'demo-read-project', assignmentId: 'demo-assignment', toolName: 'read_file' });
    this.emit(sessionId, 'artifact.diff_updated', implementationAgent.id, {
      artifactId: 'demo-diff', assignmentId: 'demo-assignment', filePath: 'src/components/example.tsx', additions: 4, deletions: 1, byteLength: 220,
    });
    this.emit(sessionId, 'tool.completed', implementationAgent.id, {
      toolExecutionId: 'demo-read-project', assignmentId: 'demo-assignment', status: 'succeeded', resultSummary: 'Read the project context and prepared a compact diff summary.', durationMs: 120, artifactIds: ['demo-diff'],
    });
    this.emit(sessionId, 'usage.updated', implementationAgent.id, { scopeId: 'demo-assignment', inputTokens: 120, outputTokens: 60, normalizedCost: 0.002, durationMs: 120 });
    this.emit(sessionId, 'handoff.created', planningAgent.id, {
      handoffId: 'demo-handoff', sourceAssignmentId: 'demo-assignment', targetAgentId: implementationAgent.id, summary: 'The scoped plan and diff summary are ready for implementation.', artifactIds: ['demo-diff'],
    });
  }

  private approval(sessionId: string, implementationAgent: SimulatorAgent): void {
    this.participant(sessionId, implementationAgent, 'waiting', 'Waiting for workspace permission');
    this.emit(sessionId, 'approval.requested', implementationAgent.id, {
      approvalId: 'demo-approval', capability: 'workspace_write', scopeSummary: 'Write an isolated workspace change.', assignmentId: 'demo-assignment',
    });
  }

  private transport(sessionId: string): InMemorySessionTransport {
    const transport = this.transports.get(sessionId);
    if (transport === undefined) throw new Error(`Simulator session ${sessionId} is not active.`);
    return transport;
  }

  private agentFor(sessionId: string, preferred: Exclude<AgentRole, 'coordinator'>, fallback?: SimulatorAgent): SimulatorAgent {
    const selected = this.sessionAgents.get(sessionId) ?? [];
    return selected.find((agent) => agent.role === preferred) ?? fallback ?? selected.find((agent) => agent.role !== 'coordinator') ?? coordinator;
  }

}

export const eventSimulator = new EventSimulator();

function toSimulatorAgent(agent: AgentInstance): SimulatorAgent {
  return { id: agent.id, role: agent.role };
}
