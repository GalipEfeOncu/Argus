// ============================================================
// ARGUS — Versioned Shared-Room Event Contract
// ============================================================

import type { AgentRole, AgentStatus, DiffBlock, ToolCallEvent } from './agent';
import type { SessionStatus, TokenUsage } from './session';

export type SessionEventType =
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

export interface SessionEvent<TType extends SessionEventType, TPayload> {
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

export interface SessionSnapshotPayload {
  status: SessionStatus;
  lastSequence: number;
}

export interface SessionStatusPayload {
  status: SessionStatus;
  reason?: string;
}

export interface ParticipantStatusPayload {
  role: AgentRole;
  status: AgentStatus;
  action?: string;
}

export interface MessageCreatedPayload {
  messageId: string;
  role: 'agent' | 'user' | 'system';
  agentRole?: AgentRole;
  content: string;
  streaming?: boolean;
}

export interface MessageDeltaPayload {
  messageId: string;
  content: string;
}

export interface MessageCompletedPayload {
  messageId: string;
}

export interface ToolPayload {
  messageId: string;
  role: AgentRole;
  toolCall: ToolCallEvent;
}

export interface ToolCompletedPayload {
  messageId: string;
  toolCallId: string;
  result: string;
  duration?: number;
  success: boolean;
}

export interface ApprovalPayload {
  approvalId: string;
  reason: string;
  message: string;
  requestedBy: AgentRole;
}

export interface DiffPayload {
  messageId: string;
  diff: DiffBlock;
}

export interface UsagePayload {
  role: AgentRole;
  usage: Partial<TokenUsage>;
}

export interface ErrorPayload {
  message: string;
  recoverable: boolean;
}

export type ArgusSessionEvent =
  | SessionEvent<'session.snapshot', SessionSnapshotPayload>
  | SessionEvent<'session.status_changed', SessionStatusPayload>
  | SessionEvent<'participant.status_changed', ParticipantStatusPayload>
  | SessionEvent<'message.created', MessageCreatedPayload>
  | SessionEvent<'message.delta', MessageDeltaPayload>
  | SessionEvent<'message.completed', MessageCompletedPayload>
  | SessionEvent<'tool.requested' | 'tool.started', ToolPayload>
  | SessionEvent<'tool.completed', ToolCompletedPayload>
  | SessionEvent<'approval.requested' | 'approval.resolved', ApprovalPayload>
  | SessionEvent<'artifact.diff_updated', DiffPayload>
  | SessionEvent<'usage.updated', UsagePayload>
  | SessionEvent<'error.created', ErrorPayload>

export interface SessionCommand<TType extends string, TPayload> {
  commandId: string;
  type: TType;
  payload: TPayload;
}

export type ArgusSessionCommand =
  | SessionCommand<'message.send', { content: string; mentions?: AgentRole[] }>
  | SessionCommand<'session.pause' | 'session.resume' | 'session.cancel', Record<string, never>>
  | SessionCommand<'participant.interrupt', { role: AgentRole }>
  | SessionCommand<'approval.resolve', { approvalId: string; approved: boolean; feedback?: string }>;
