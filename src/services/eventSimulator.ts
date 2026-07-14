import type { AgentInfo, AgentRole, ModelRef, ToolCallEvent } from '@/types/agent';
import type { ArgusSessionEvent, MessageCreatedPayload } from '@/types/events';
import { useAgentStore } from '@/stores/agentStore';
import { useSessionStore } from '@/stores/sessionStore';

const demoModel: ModelRef = {
  providerId: 'demo',
  modelId: 'argus-simulator',
  displayName: 'Argus Simulator',
};

const demoRoles: AgentRole[] = ['coordinator', 'planner', 'builder', 'reviewer', 'tester', 'ui_agent'];

class EventSimulator {
  private activeSessions = new Set<string>();
  private timers = new Map<string, ReturnType<typeof setTimeout>[]>();
  private sequences = new Map<string, number>();

  isActive(sessionId: string): boolean {
    return this.activeSessions.has(sessionId);
  }

  start(sessionId: string): void {
    if (this.activeSessions.has(sessionId)) return;

    this.activeSessions.add(sessionId);
    this.sequences.set(sessionId, 0);
    this.timers.set(sessionId, []);

    const agents: AgentInfo[] = demoRoles.map((role) => ({
      role,
      status: 'idle',
      modelRef: demoModel,
      tokenCount: 0,
    }));
    useAgentStore.getState().initAgents(agents);
    this.emit(sessionId, 'session.status_changed', 'system', { status: 'running' });
    this.schedule(sessionId, 350, () => this.participant(sessionId, 'coordinator', 'thinking', 'Reviewing the task and available team capabilities'));
    this.schedule(sessionId, 650, () => this.message(sessionId, 'coordinator', 'I will coordinate this session in the open. I’m assigning planning first, then I’ll request implementation and review.'));
    this.schedule(sessionId, 1200, () => this.participant(sessionId, 'planner', 'thinking', 'Mapping the project and acceptance criteria'));
    this.schedule(sessionId, 1600, () => this.message(sessionId, 'planner', 'I will inspect the relevant project files, identify the smallest safe change, and hand the implementation plan to Builder.'));
    this.schedule(sessionId, 2200, () => this.participant(sessionId, 'builder', 'using_tool', 'Reading project context'));
    this.schedule(sessionId, 2500, () => this.tool(sessionId));
    this.schedule(sessionId, 3300, () => this.approval(sessionId));
  }

  stop(sessionId: string): void {
    (this.timers.get(sessionId) ?? []).forEach(clearTimeout);
    this.timers.delete(sessionId);
    this.sequences.delete(sessionId);
    this.activeSessions.delete(sessionId);
  }

  sendHumanMessage(sessionId: string, content: string): void {
    if (!this.isActive(sessionId)) return;
    this.emit(sessionId, 'message.created', 'human', {
      messageId: crypto.randomUUID(),
      role: 'user',
      content,
    });
    this.schedule(sessionId, 300, () => this.message(sessionId, 'coordinator', 'Acknowledged. I added your instruction to the active assignment and will keep it visible to the team.'));
  }

  resolveApproval(sessionId: string, approved: boolean): void {
    if (!this.isActive(sessionId)) return;
    useAgentStore.getState().setInterrupted(false);
    this.emit(sessionId, 'approval.resolved', 'human', {
      approvalId: 'demo-approval',
      reason: approved ? 'approved' : 'rejected',
      message: approved ? 'User approved the requested workspace action.' : 'User rejected the requested workspace action.',
      requestedBy: 'builder',
    });
    this.emit(sessionId, 'session.status_changed', 'system', { status: 'running' });
    this.participant(sessionId, 'builder', approved ? 'using_tool' : 'thinking', approved ? 'Applying an isolated workspace change' : 'Replanning after user feedback');
    this.schedule(sessionId, 600, () => this.message(sessionId, 'builder', approved ? 'The change was applied in the isolated workspace. I am preparing a diff for review.' : 'I will revise the approach before making a workspace change.'));
  }

  private schedule(sessionId: string, delay: number, action: () => void): void {
    const timer = setTimeout(action, delay);
    this.timers.get(sessionId)?.push(timer);
  }

  private nextEvent<TType extends ArgusSessionEvent['type'], TPayload>(
    sessionId: string,
    type: TType,
    actorId: string,
    payload: TPayload,
  ): Extract<ArgusSessionEvent, { type: TType }> {
    const sequence = (this.sequences.get(sessionId) ?? 0) + 1;
    this.sequences.set(sessionId, sequence);
    return {
      version: 1,
      eventId: crypto.randomUUID(),
      sessionId,
      sequence,
      timestamp: Date.now(),
      type,
      actorId,
      payload,
    } as unknown as Extract<ArgusSessionEvent, { type: TType }>;
  }

  private emit<TType extends ArgusSessionEvent['type'], TPayload>(sessionId: string, type: TType, actorId: string, payload: TPayload): void {
    this.apply(this.nextEvent(sessionId, type, actorId, payload));
  }

  private apply(event: ArgusSessionEvent): void {
    const agentStore = useAgentStore.getState();
    const sessionStore = useSessionStore.getState();

    switch (event.type) {
      case 'session.status_changed':
        sessionStore.updateSessionStatus(event.sessionId, event.payload.status);
        break;
      case 'participant.status_changed':
        agentStore.updateAgentStatus(event.payload.role, event.payload.status, event.payload.action);
        break;
      case 'message.created': {
        const payload = event.payload as MessageCreatedPayload;
        agentStore.addMessage({
          id: payload.messageId,
          role: payload.role,
          agentRole: payload.agentRole,
          content: payload.content,
          isStreaming: Boolean(payload.streaming),
          timestamp: event.timestamp,
        });
        break;
      }
      case 'tool.requested':
      case 'tool.started':
        agentStore.addToolCallToMessage(event.payload.messageId, event.payload.toolCall);
        break;
      case 'approval.requested':
        agentStore.setInterrupted(true, event.payload.message);
        sessionStore.updateSessionStatus(event.sessionId, 'waiting_approval');
        break;
      case 'approval.resolved':
        agentStore.setInterrupted(false);
        break;
      default:
        break;
    }
  }

  private participant(sessionId: string, role: AgentRole, status: AgentInfo['status'], action: string): void {
    this.emit(sessionId, 'participant.status_changed', role, { role, status, action });
  }

  private message(sessionId: string, role: AgentRole, content: string): void {
    this.emit(sessionId, 'message.created', role, {
      messageId: crypto.randomUUID(),
      role: 'agent',
      agentRole: role,
      content,
    });
    this.participant(sessionId, role, 'done', 'Shared an update');
  }

  private tool(sessionId: string): void {
    const messageId = crypto.randomUUID();
    const toolCall: ToolCallEvent = {
      id: 'demo-read-project',
      tool: 'read_file',
      args: { path: 'README.md' },
      status: 'running',
    };
    this.emit(sessionId, 'message.created', 'builder', {
      messageId,
      role: 'agent',
      agentRole: 'builder',
      content: 'I am reading the current project context before proposing a change.',
    });
    this.emit(sessionId, 'tool.requested', 'builder', { messageId, role: 'builder', toolCall });
  }

  private approval(sessionId: string): void {
    this.participant(sessionId, 'builder', 'waiting_approval', 'Waiting for workspace permission');
    this.emit(sessionId, 'approval.requested', 'builder', {
      approvalId: 'demo-approval',
      reason: 'workspace_write',
      message: 'Builder requests permission to write an isolated workspace change.',
      requestedBy: 'builder',
    });
  }
}

export const eventSimulator = new EventSimulator();
