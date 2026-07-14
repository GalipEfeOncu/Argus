// ============================================================
// ARGUS — Session Type Definitions
// ============================================================

import type { AgentRole, Message } from './agent';
import type { RoleConfig } from './agent';

export type SessionStatus =
  | 'setup'
  | 'preparing'
  | 'running'
  | 'paused'
  | 'waiting_approval'
  | 'completed'
  | 'cancelled'
  | 'error';

export interface Session {
  id: string;
  name: string;
  projectPath: string;
  task: string;
  status: SessionStatus;
  roleConfigs: RoleConfig[];
  messages: Message[];
  activeAgent?: AgentRole;
  startedAt: number;
  completedAt?: number;
  tokenUsage: TokenUsage;
}

export interface SessionConfig {
  projectPath: string;
  task: string;
  roleConfigs: RoleConfig[];
  name?: string;
}

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

// ── WebSocket Events ─────────────────────────────────────────

export type WSEventType =
  | 'agent_start'
  | 'agent_done'
  | 'token'
  | 'tool_call_start'
  | 'tool_call_result'
  | 'diff'
  | 'interrupt'
  | 'error'
  | 'session_complete';

export interface WSEvent {
  type: WSEventType;
  sessionId: string;
  agentRole?: AgentRole;
  content?: string;
  data?: Record<string, unknown>;
  timestamp: number;
}

export interface InterruptEvent {
  type: 'interrupt';
  reason: 'human_review' | 'approval_needed' | 'error';
  message: string;
}
