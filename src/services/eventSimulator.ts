import type { AgentInfo, AgentRole, ModelRef } from '@/types/agent';
import type { ArgusSessionCommand, ArgusSessionEvent } from '@/types/events';
import { useAgentStore } from '@/stores/agentStore';
import { InMemorySessionTransport, SessionStreamClient } from './sessionTransport';
import type { ProjectedParticipant, SessionProjection } from './sessionProjection';
import { syncLegacyProjection } from './legacyProjectionBridge';

const demoModel: ModelRef = {
  providerId: 'demo',
  modelId: 'argus-simulator',
  displayName: 'Argus Simulator',
};

const demoRoles: AgentRole[] = ['coordinator', 'planner', 'builder', 'reviewer', 'tester', 'ui_agent'];
type SimulatorTimer = ReturnType<typeof setTimeout>;

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

  constructor(private readonly dependencies: EventSimulatorDependencies = browserSimulatorDependencies) {}

  isActive(sessionId: string): boolean {
    return this.clients.has(sessionId);
  }

  getProjection(sessionId: string): SessionProjection | undefined {
    return this.clients.get(sessionId)?.getProjection();
  }

  start(sessionId: string): void {
    if (this.isActive(sessionId)) return;

    const transport = new InMemorySessionTransport();
    const client = new SessionStreamClient(transport, sessionId, this.dependencies.clock);
    const agents: AgentInfo[] = demoRoles.map((role) => ({
      role,
      status: 'idle',
      modelRef: demoModel,
      tokenCount: 0,
    }));
    useAgentStore.getState().initAgents(agents);
    this.transports.set(sessionId, transport);
    this.clients.set(sessionId, client);
    this.sequences.set(sessionId, 0);
    this.timers.set(sessionId, []);
    this.unsubscribeProjection.set(sessionId, client.subscribe((projection) => syncLegacyProjection(sessionId, projection)));
    client.connect();

    this.snapshot(sessionId, 'running');
    this.schedule(sessionId, 350, () => this.participant(sessionId, 'coordinator', 'working', 'Reviewing the task and available team capabilities'));
    this.schedule(sessionId, 650, () => this.message(sessionId, 'coordinator', 'I will coordinate this session in the open. I’m assigning planning first, then I’ll request implementation and review.'));
    this.schedule(sessionId, 1200, () => this.participant(sessionId, 'planner', 'working', 'Mapping the project and acceptance criteria'));
    this.schedule(sessionId, 1600, () => this.message(sessionId, 'planner', 'I will inspect the relevant project files, identify the smallest safe change, and hand the implementation plan to Builder.'));
    this.schedule(sessionId, 2200, () => this.participant(sessionId, 'builder', 'working', 'Reading project context'));
    this.schedule(sessionId, 2500, () => this.tool(sessionId));
    this.schedule(sessionId, 3300, () => this.approval(sessionId));
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
  }

  sendHumanMessage(sessionId: string, content: string): void {
    const client = this.clients.get(sessionId);
    if (client === undefined) return;
    const commandId = this.dependencies.createId();
    client.send({ commandId, type: 'message.send', payload: { content } });
    this.emit(sessionId, 'message.created', 'human', {
      messageId: this.dependencies.createId(), authorId: 'human', authorKind: 'human', content,
    }, commandId);
    this.schedule(sessionId, 300, () => this.message(sessionId, 'coordinator', 'Acknowledged. I added your instruction to the active assignment and will keep it visible to the team.'));
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
    this.participant(sessionId, 'builder', 'working', approved ? 'Applying an isolated workspace change' : 'Replanning after user feedback');
    this.schedule(sessionId, 600, () => this.message(sessionId, 'builder', approved ? 'The change was applied in the isolated workspace. I am preparing a diff for review.' : 'I will revise the approach before making a workspace change.'));
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

  private participant(sessionId: string, id: AgentRole, status: ProjectedParticipant['status'], actionSummary: string): void {
    this.emit(sessionId, 'participant.status_changed', id, {
      participantId: id, participantKind: id === 'coordinator' ? 'coordinator' : 'agent', status, actionSummary,
    });
  }

  private message(sessionId: string, authorId: AgentRole, content: string): void {
    this.emit(sessionId, 'message.created', authorId, {
      messageId: this.dependencies.createId(), authorId, authorKind: authorId === 'coordinator' ? 'coordinator' : 'agent', content,
    });
    this.participant(sessionId, authorId, 'stopped', 'Shared an update');
  }

  private tool(sessionId: string): void {
    this.emit(sessionId, 'message.created', 'builder', {
      messageId: this.dependencies.createId(), authorId: 'builder', authorKind: 'agent', content: 'I am reading the current project context before proposing a change.',
    });
    this.emit(sessionId, 'tool.requested', 'builder', {
      toolExecutionId: 'demo-read-project', assignmentId: 'demo-assignment', toolName: 'read_file', operationClass: 'read_only', requestSummary: 'Read the current project context.',
    });
  }

  private approval(sessionId: string): void {
    this.participant(sessionId, 'builder', 'waiting', 'Waiting for workspace permission');
    this.emit(sessionId, 'approval.requested', 'builder', {
      approvalId: 'demo-approval', capability: 'workspace_write', scopeSummary: 'Write an isolated workspace change.', assignmentId: 'demo-assignment',
    });
  }

  private transport(sessionId: string): InMemorySessionTransport {
    const transport = this.transports.get(sessionId);
    if (transport === undefined) throw new Error(`Simulator session ${sessionId} is not active.`);
    return transport;
  }

}

export const eventSimulator = new EventSimulator();
