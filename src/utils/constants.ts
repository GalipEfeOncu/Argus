import type { AgentRole } from '@/types/agent';

export const AGENT_ROLES: AgentRole[] = [
  'planner',
  'builder',
  'reviewer',
  'tester',
  'ui_agent',
];

export const MAX_RECONNECT_ATTEMPTS = 5;
export const RECONNECT_DELAY_MS = 3000;

export const APP_NAME = 'Argus';
export const APP_VERSION = '0.1.0';
