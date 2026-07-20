import type { AgentStatus, Message } from '@/types/agent';
import type { SessionStatus } from '@/types/session';
import { useAgentStore } from '@/stores/agentStore';
import { useSessionStore } from '@/stores/sessionStore';
import type { ProjectedParticipant, SessionProjection } from './sessionProjection';

/** Temporary adapter while Phase 1.2 migrates the existing UI stores to the projection directly. */
export function syncLegacyProjection(sessionId: string, projection: SessionProjection): void {
  const messages: Message[] = Object.values(projection.messages).map((message) => ({
    id: message.id,
    role: message.authorKind === 'human' ? 'user' : message.authorKind === 'system' ? 'system' : 'agent',
    ...(agentRoleForId(message.authorId) !== undefined ? { agentRole: agentRoleForId(message.authorId) } : {}),
    content: message.content,
    isStreaming: message.streaming,
    timestamp: Date.parse(message.timestamp),
  }));
  useAgentStore.setState({
    messages,
    isInterrupted: projection.status === 'waiting_approval',
    interruptReason: projection.status === 'waiting_approval' ? 'Waiting for approval' : undefined,
  });
  for (const participant of Object.values(projection.participants)) {
    if (useAgentStore.getState().agents[participant.id] !== undefined) {
      useAgentStore.getState().updateAgentStatus(participant.id, toLegacyAgentStatus(participant.status), participant.actionSummary);
    }
  }
  if (projection.status !== null) useSessionStore.getState().updateSessionStatus(sessionId, toLegacySessionStatus(projection.status));
  if (projection.lastAcceptedConfigurationPatch !== null) useSessionStore.getState().patchSessionConfiguration(sessionId, projection.lastAcceptedConfigurationPatch);
}

function agentRoleForId(instanceId: string) {
  return useAgentStore.getState().agents[instanceId]?.role;
}

function toLegacyAgentStatus(status: ProjectedParticipant['status']): AgentStatus {
  switch (status) {
    case 'working': return 'thinking';
    case 'waiting': return 'waiting_approval';
    case 'errored': return 'error';
    case 'stopped': return 'done';
    default: return 'idle';
  }
}

function toLegacySessionStatus(status: string): SessionStatus {
  switch (status) {
    case 'created': return 'setup';
    case 'failed':
    case 'completed_partial': return status;
    case 'waiting_decision': return status;
    case 'preparing':
    case 'running':
    case 'paused':
    case 'waiting_approval':
    case 'completed':
    case 'cancelled': return status;
    default: return 'error';
  }
}
