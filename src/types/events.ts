// Canonical target wire contracts are generated from backend Pydantic schemas.
export type {
  ArgusSessionEvent,
  MessageCreatedPayload,
} from './generated/session-events';
export type { ArgusSessionCommand } from './generated/session-commands';

/**
 * Legacy live-WebSocket and simulator shapes. These are intentionally separate
 * from the canonical shared-room envelope while the transport migration is in progress.
 */
import type { AgentRole, AgentStatus, DiffBlock, ToolCallEvent } from './agent';
import type { SessionStatus, TokenUsage } from './session';

export type LegacySessionEventType =
  | 'session.snapshot'
  | 'session.status_changed'
  | 'participant.status_changed'
  | 'message.created'
  | 'message.delta'
  | 'message.completed'
  | 'assignment.created'
  | 'handoff.created'
  | 'tool.requested'
  | 'tool.started'
  | 'tool.completed'
  | 'approval.requested'
  | 'approval.resolved'
  | 'artifact.diff_updated'
  | 'usage.updated'
  | 'error.created';

export interface LegacySessionEvent<TType extends LegacySessionEventType, TPayload> {
  version: 1;
  eventId: string;
  sessionId: string;
  sequence: number;
  timestamp: number;
  type: TType;
  actorId: string;
  correlationId?: string;
  payload: TPayload;
}

export interface LegacySessionSnapshotPayload {
  status: SessionStatus;
  lastSequence: number;
}

export interface LegacySessionStatusPayload {
  status: SessionStatus;
  reason?: string;
}

export interface LegacyParticipantStatusPayload {
  role: AgentRole;
  status: AgentStatus;
  action?: string;
}

export interface LegacyMessageCreatedPayload {
  messageId: string;
  role: 'agent' | 'user' | 'system';
  agentRole?: AgentRole;
  content: string;
  streaming?: boolean;
}

export interface LegacyMessageDeltaPayload {
  messageId: string;
  content: string;
}

export interface LegacyMessageCompletedPayload {
  messageId: string;
}

export interface LegacyToolPayload {
  messageId: string;
  role: AgentRole;
  toolCall: ToolCallEvent;
}

export interface LegacyToolCompletedPayload {
  messageId: string;
  toolCallId: string;
  result: string;
  duration?: number;
  success: boolean;
}

export interface LegacyApprovalPayload {
  approvalId: string;
  reason: string;
  message: string;
  requestedBy: AgentRole;
}

export interface LegacyDiffPayload {
  messageId: string;
  diff: DiffBlock;
}

export interface LegacyUsagePayload {
  role: AgentRole;
  usage: Partial<TokenUsage>;
}

export interface LegacyErrorPayload {
  message: string;
  recoverable: boolean;
}

export type LegacySessionEventUnion =
  | LegacySessionEvent<'session.snapshot', LegacySessionSnapshotPayload>
  | LegacySessionEvent<'session.status_changed', LegacySessionStatusPayload>
  | LegacySessionEvent<'participant.status_changed', LegacyParticipantStatusPayload>
  | LegacySessionEvent<'message.created', LegacyMessageCreatedPayload>
  | LegacySessionEvent<'message.delta', LegacyMessageDeltaPayload>
  | LegacySessionEvent<'message.completed', LegacyMessageCompletedPayload>
  | LegacySessionEvent<'tool.requested' | 'tool.started', LegacyToolPayload>
  | LegacySessionEvent<'tool.completed', LegacyToolCompletedPayload>
  | LegacySessionEvent<'approval.requested' | 'approval.resolved', LegacyApprovalPayload>
  | LegacySessionEvent<'artifact.diff_updated', LegacyDiffPayload>
  | LegacySessionEvent<'usage.updated', LegacyUsagePayload>
  | LegacySessionEvent<'error.created', LegacyErrorPayload>;
