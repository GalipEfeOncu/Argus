// ============================================================
// ARGUS — Session Type Definitions
// ============================================================

import type { AgentRole, Message } from './agent';
import type { RoleConfig } from './agent';
import type { ModelRef } from './agent';

export type SessionStatus =
  | 'setup'
  | 'preparing'
  | 'running'
  | 'paused'
  | 'waiting_approval'
  | 'waiting_decision'
  | 'completed'
  | 'completed_partial'
  | 'cancelled'
  | 'failed'
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
  configuration: SessionConfiguration;
}

export interface SessionConfig {
  projectPath: string;
  task: string;
  roleConfigs: RoleConfig[];
  configuration: SessionConfiguration;
  name?: string;
}

export type SessionPreset = 'quick' | 'balanced' | 'thorough' | 'custom';
export type WorkspaceMode = 'worktree' | 'snapshot' | 'direct_write';
export type OutputLanguage = 'en' | 'tr';
export type RequiredRoleApplicability = 'always' | 'when_changes' | 'when_capability_used';
export type PermissionProfile = 'strict' | 'balanced' | 'autonomous' | 'expert_unrestricted';
export type ApprovalBehavior = 'ask_each_time' | 'ask_by_policy' | 'preauthorize_session' | 'deny_interactive';
export type LimitResolution = 'ask_user' | 'coordinator_decides' | 'stop';

export interface AgentInstance {
  id: string;
  role: Exclude<AgentRole, 'coordinator'>;
  label: string;
  modelRef: ModelRef | null;
  capabilities: string[];
}

export interface RequiredRoleRule {
  id: string;
  role: AgentInstance['role'];
  applicability: RequiredRoleApplicability;
  successEvidence: string;
  minimumCompletions: number;
  capability?: string;
}

export interface ExecutionLimits {
  maxRevisionsPerFinding: number | null;
  maxAssignmentAttempts: number | null;
  maxModelIterationsPerAssignment: number | null;
  maxToolCallsPerAssignment: number | null;
  maxSessionTokens: number | null;
  maxSessionCost: number | null;
  maxWallClockSeconds: number | null;
  maxParallelReadOnlyAssignments: number | null;
  softWarningRatio: number;
}

export interface ApprovalPolicy {
  permissionProfile: PermissionProfile;
  behavior: ApprovalBehavior;
  preauthorizedCapabilities: string[];
  limitResolution: LimitResolution;
}

/** The client-side, Phase 1 configuration snapshot. Phase 2 persists this shape. */
export interface SessionConfiguration {
  preset: SessionPreset;
  workspaceMode: WorkspaceMode;
  outputLanguage: OutputLanguage;
  coordinatorModel: ModelRef | null;
  coordinatorPromptOverride: string;
  enabledSkills: string[];
  directWriteAcknowledged: boolean;
  preauthorizationAcknowledged: boolean;
  preauthorizationScope: string;
  availableAgents: AgentInstance[];
  availableAgentIds: string[];
  requiredRoleRules: RequiredRoleRule[];
  executionLimits: ExecutionLimits;
  approvalPolicy: ApprovalPolicy;
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
