// ============================================================
// ARGUS — Agent & Role Type Definitions
// ============================================================

export type AgentRole = 'planner' | 'builder' | 'reviewer' | 'tester' | 'ui_agent';

export type AgentStatus =
  | 'idle'
  | 'thinking'
  | 'streaming'
  | 'using_tool'
  | 'waiting_approval'
  | 'done'
  | 'error';

export interface AgentInfo {
  role: AgentRole;
  status: AgentStatus;
  modelRef: ModelRef;
  currentAction?: string;
  tokenCount: number;
}

export interface ModelRef {
  providerId: string;
  modelId: string;
  displayName: string;
}

// ── Messages ────────────────────────────────────────────────

export type MessageRole = 'agent' | 'user' | 'system' | 'tool';

export interface Message {
  id: string;
  role: MessageRole;
  agentRole?: AgentRole;
  content: string;
  isStreaming: boolean;
  timestamp: number;
  toolCalls?: ToolCallEvent[];
  diffBlocks?: DiffBlock[];
  metadata?: Record<string, unknown>;
}

// ── Tool Calls ───────────────────────────────────────────────

export type ToolName =
  | 'read_file'
  | 'write_file'
  | 'edit_file'
  | 'list_dir'
  | 'search_files'
  | 'shell_exec'
  | 'git_status'
  | 'git_diff'
  | 'git_commit';

export interface ToolCallEvent {
  id: string;
  tool: ToolName;
  args: Record<string, unknown>;
  result?: string;
  status: 'pending' | 'running' | 'success' | 'error';
  duration?: number;
}

// ── Diff ────────────────────────────────────────────────────

export interface DiffBlock {
  filePath: string;
  before: string;
  after: string;
  additions: number;
  deletions: number;
}

// ── Role Config ──────────────────────────────────────────────

export interface RoleConfig {
  role: AgentRole;
  enabled: boolean;
  modelRef: ModelRef;
  customSystemPrompt?: string;
}

// ── Agent Role Metadata (display info) ──────────────────────

export const AGENT_ROLE_META: Record<AgentRole, {
  label: string;
  emoji: string;
  description: string;
  colorVar: string;
}> = {
  planner: {
    label: 'Planner',
    emoji: '🧭',
    description: 'Analyzes the task and creates a step-by-step plan',
    colorVar: '--agent-planner',
  },
  builder: {
    label: 'Builder',
    emoji: '🔨',
    description: 'Implements the plan by writing and editing code',
    colorVar: '--agent-builder',
  },
  reviewer: {
    label: 'Reviewer',
    emoji: '🔍',
    description: 'Reviews code for bugs, security issues, and quality',
    colorVar: '--agent-reviewer',
  },
  tester: {
    label: 'Tester',
    emoji: '🧪',
    description: 'Writes and runs tests to verify the implementation',
    colorVar: '--agent-tester',
  },
  ui_agent: {
    label: 'UI Agent',
    emoji: '🎨',
    description: 'Handles UI/UX design, CSS, and component styling',
    colorVar: '--agent-ui',
  },
};
