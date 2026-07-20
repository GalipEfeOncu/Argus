import type { AgentRole, ModelRef } from '@/types/agent';
import type {
  AgentInstance, ExecutionLimits, RequiredRoleRule, SessionConfiguration, SessionPreset,
} from '@/types/session';

const fallbackModel: ModelRef = {
  providerId: 'builtin', modelId: 'argus-default', displayName: 'Argus default model',
};

const agentCapabilities: Record<Exclude<AgentRole, 'coordinator'>, string[]> = {
  planner: ['workspace.read'],
  builder: ['workspace.read', 'workspace.write', 'test.run'],
  reviewer: ['workspace.read'],
  tester: ['workspace.read', 'test.run'],
  ui_agent: ['workspace.read', 'workspace.write'],
};

const agentLabels: Record<Exclude<AgentRole, 'coordinator'>, string> = {
  planner: 'Planner', builder: 'Builder', reviewer: 'Reviewer', tester: 'Tester', ui_agent: 'UI Agent',
};

const supportedEvidence = new Set(['approved_review', 'passing_test_run', 'accepted_plan', 'verified_change']);

export const limitDefinitions: ReadonlyArray<{ key: keyof ExecutionLimits; label: string; unit: string; zeroMeaning: string }> = [
  { key: 'maxRevisionsPerFinding', label: 'Revisions per finding', unit: 'revisions', zeroMeaning: '0 blocks revisions' },
  { key: 'maxAssignmentAttempts', label: 'Assignment attempts', unit: 'attempts', zeroMeaning: '0 blocks new assignments' },
  { key: 'maxModelIterationsPerAssignment', label: 'Model iterations', unit: 'iterations / assignment', zeroMeaning: '0 blocks model work' },
  { key: 'maxToolCallsPerAssignment', label: 'Tool calls', unit: 'calls / assignment', zeroMeaning: '0 blocks tool calls' },
  { key: 'maxSessionTokens', label: 'Session tokens', unit: 'tokens', zeroMeaning: '0 blocks token use' },
  { key: 'maxSessionCost', label: 'Session cost', unit: 'USD', zeroMeaning: '0 blocks paid model use' },
  { key: 'maxWallClockSeconds', label: 'Wall clock', unit: 'seconds', zeroMeaning: '0 stops work immediately' },
  { key: 'maxParallelReadOnlyAssignments', label: 'Parallel read-only work', unit: 'assignments', zeroMeaning: '0 blocks parallel read-only work' },
];

export function createAgentInstances(defaultRoleModels: Partial<Record<AgentRole, ModelRef>>): AgentInstance[] {
  return (Object.keys(agentLabels) as AgentInstance['role'][]).map((role) => ({
    id: `builtin-${role}`,
    role,
    label: agentLabels[role],
    modelRef: defaultRoleModels[role] ?? fallbackModel,
    capabilities: agentCapabilities[role],
  }));
}

const balancedLimits: ExecutionLimits = {
  maxRevisionsPerFinding: 3, maxAssignmentAttempts: 8, maxModelIterationsPerAssignment: 20,
  maxToolCallsPerAssignment: 100, maxSessionTokens: 500_000, maxSessionCost: null,
  maxWallClockSeconds: 14_400, maxParallelReadOnlyAssignments: 3, softWarningRatio: 0.8,
};

function rule(role: RequiredRoleRule['role'], applicability: RequiredRoleRule['applicability'], evidence: string): RequiredRoleRule {
  return { id: `gate-${role}`, role, applicability, successEvidence: evidence, minimumCompletions: 1 };
}

export function createConfiguration(
  defaultRoleModels: Partial<Record<AgentRole, ModelRef>>,
  preset: SessionPreset = 'balanced',
): SessionConfiguration {
  const availableAgents = createAgentInstances(defaultRoleModels);
  const base: SessionConfiguration = {
    preset: 'custom', workspaceMode: 'worktree', outputLanguage: 'en',
    coordinatorModel: defaultRoleModels.coordinator ?? fallbackModel, coordinatorPromptOverride: '', enabledSkills: [], directWriteAcknowledged: false,
    preauthorizationAcknowledged: false, preauthorizationScope: '', availableAgents,
    availableAgentIds: availableAgents.map((agent) => agent.id), requiredRoleRules: [],
    executionLimits: balancedLimits,
    approvalPolicy: { permissionProfile: 'balanced', behavior: 'ask_by_policy', preauthorizedCapabilities: [], limitResolution: 'coordinator_decides' },
  };
  return preset === 'custom' ? base : applyPreset(base, preset);
}

export function applyPreset(configuration: SessionConfiguration, preset: Exclude<SessionPreset, 'custom'>): SessionConfiguration {
  const idsFor = (roles: AgentInstance['role'][]) => configuration.availableAgents
    .filter((agent) => roles.includes(agent.role)).map((agent) => agent.id);
  const presets: Record<Exclude<SessionPreset, 'custom'>, Omit<SessionConfiguration, 'availableAgents' | 'coordinatorModel' | 'coordinatorPromptOverride' | 'enabledSkills' | 'outputLanguage' | 'directWriteAcknowledged' | 'preauthorizationAcknowledged' | 'preauthorizationScope'>> = {
    quick: {
      preset: 'quick', workspaceMode: 'worktree', availableAgentIds: idsFor(['builder']), requiredRoleRules: [],
      executionLimits: { ...balancedLimits, maxRevisionsPerFinding: 0, maxAssignmentAttempts: 3, maxModelIterationsPerAssignment: 8, maxToolCallsPerAssignment: 30, maxSessionTokens: 100_000, maxWallClockSeconds: 3_600, maxParallelReadOnlyAssignments: 1 },
      approvalPolicy: { permissionProfile: 'balanced', behavior: 'ask_by_policy', preauthorizedCapabilities: [], limitResolution: 'stop' },
    },
    balanced: {
      preset: 'balanced', workspaceMode: 'worktree', availableAgentIds: idsFor(['planner', 'builder', 'reviewer', 'tester', 'ui_agent']),
      requiredRoleRules: [rule('reviewer', 'when_changes', 'approved_review'), rule('tester', 'when_changes', 'passing_test_run')], executionLimits: balancedLimits,
      approvalPolicy: { permissionProfile: 'balanced', behavior: 'ask_by_policy', preauthorizedCapabilities: [], limitResolution: 'coordinator_decides' },
    },
    thorough: {
      preset: 'thorough', workspaceMode: 'worktree', availableAgentIds: idsFor(['planner', 'builder', 'reviewer', 'tester', 'ui_agent']),
      requiredRoleRules: [rule('reviewer', 'always', 'approved_review'), rule('tester', 'when_changes', 'passing_test_run')],
      executionLimits: { ...balancedLimits, maxRevisionsPerFinding: 5, maxAssignmentAttempts: 12, maxModelIterationsPerAssignment: 32, maxToolCallsPerAssignment: 160, maxSessionTokens: 1_000_000, maxWallClockSeconds: 28_800, maxParallelReadOnlyAssignments: 4 },
      approvalPolicy: { permissionProfile: 'balanced', behavior: 'ask_by_policy', preauthorizedCapabilities: [], limitResolution: 'ask_user' },
    },
  };
  return { ...configuration, ...presets[preset], executionLimits: { ...presets[preset].executionLimits }, approvalPolicy: { ...presets[preset].approvalPolicy }, requiredRoleRules: [...presets[preset].requiredRoleRules] };
}

export function markCustom(configuration: SessionConfiguration): SessionConfiguration {
  return { ...configuration, preset: 'custom' };
}

export function roleEvidence(role: AgentInstance['role']): string {
  return role === 'reviewer' ? 'approved_review' : role === 'tester' ? 'passing_test_run' : role === 'planner' ? 'accepted_plan' : 'verified_change';
}

export function validateConfiguration(configuration: SessionConfiguration): string[] {
  const errors: string[] = [];
  if (configuration.coordinatorModel === null) errors.push('Coordinator requires a configured model.');
  const available = new Set(configuration.availableAgentIds);
  if (available.size !== configuration.availableAgentIds.length) errors.push('Each available agent instance may be selected only once.');
  configuration.availableAgentIds.forEach((id) => {
    if (!configuration.availableAgents.some((agent) => agent.id === id)) errors.push(`Unknown available agent: ${id}.`);
  });
  configuration.availableAgents.filter((agent) => available.has(agent.id) && agent.modelRef === null).forEach((agent) => errors.push(`${agent.label} requires a configured model.`));
  configuration.requiredRoleRules.forEach((required) => {
    const eligible = configuration.availableAgents.some((agent) => agent.role === required.role && available.has(agent.id));
    if (!eligible) errors.push(`${required.role} is required but no eligible instance is available.`);
    if (!required.successEvidence.trim()) errors.push(`${required.role} needs a success evidence requirement.`);
    if (!supportedEvidence.has(required.successEvidence)) errors.push(`${required.role} uses an unsupported success evidence type.`);
    if (required.minimumCompletions < 1 || !Number.isInteger(required.minimumCompletions)) errors.push(`${required.role} must require at least one completion.`);
    if (required.applicability === 'when_capability_used' && !required.capability?.trim()) errors.push(`${required.role} requires a capability when using capability-based applicability.`);
    if (required.applicability === 'when_capability_used' && required.capability !== undefined && !configuration.availableAgents.some((agent) => available.has(agent.id) && agent.capabilities.includes(required.capability!))) errors.push(`${required.role} gate references a capability no available agent can use.`);
  });
  limitDefinitions.forEach(({ key, label }) => {
    const value = configuration.executionLimits[key];
    if (typeof value === 'number') {
      const validNumber = key === 'maxSessionCost'
        ? Number.isFinite(value) && value >= 0
        : Number.isFinite(value) && Number.isInteger(value) && value >= 0;
      if (!validNumber) errors.push(`${label} must be ${key === 'maxSessionCost' ? 'a non-negative amount' : 'a whole number'}, zero, or blank for unlimited.`);
    }
  });
  const { softWarningRatio } = configuration.executionLimits;
  if (!Number.isFinite(softWarningRatio) || softWarningRatio <= 0 || softWarningRatio > 1) errors.push('Soft warning ratio must be greater than 0 and at most 1.');
  if (configuration.requiredRoleRules.length > 0 && configuration.executionLimits.maxAssignmentAttempts === 0) errors.push('Required role gates are incompatible with zero assignment attempts.');
  if (configuration.requiredRoleRules.length > 0 && configuration.executionLimits.maxModelIterationsPerAssignment === 0) errors.push('Required role gates are incompatible with zero model iterations.');
  if (configuration.requiredRoleRules.length > 0 && configuration.executionLimits.maxSessionTokens === 0) errors.push('Required role gates are incompatible with zero session tokens.');
  if (configuration.requiredRoleRules.length > 0 && configuration.executionLimits.maxWallClockSeconds === 0) errors.push('Required role gates are incompatible with zero wall-clock time.');
  if (configuration.requiredRoleRules.some((required) => required.role === 'tester' && required.applicability === 'always') && configuration.executionLimits.maxToolCallsPerAssignment === 0) errors.push('An always-required Tester gate is incompatible with zero tool calls.');
  const policy = configuration.approvalPolicy;
  const allowedPreauthorization = policy.permissionProfile === 'autonomous'
    ? ['workspace.read', 'workspace.write', 'test.run']
    : policy.permissionProfile === 'balanced' ? ['workspace.read', 'test.run'] : [];
  if (policy.behavior !== 'preauthorize_session' && policy.preauthorizedCapabilities.length > 0) errors.push('Pre-authorized capabilities require no-interruption mode.');
  if (policy.preauthorizedCapabilities.some((capability) => !allowedPreauthorization.includes(capability))) errors.push('The selected permission profile cannot safely pre-authorize one or more capabilities.');
  if (configuration.workspaceMode === 'direct_write' && policy.preauthorizedCapabilities.includes('workspace.write')) errors.push('Direct-write work cannot pre-authorize workspace writes.');
  if (configuration.workspaceMode === 'direct_write' && !configuration.directWriteAcknowledged) errors.push('Direct-write mode requires acknowledgement that rollback is limited.');
  if (policy.behavior === 'preauthorize_session' && !configuration.preauthorizationScope.trim()) errors.push('Pre-authorized work requires an exact workspace scope.');
  if (policy.behavior === 'preauthorize_session' && policy.permissionProfile === 'autonomous' && !configuration.preauthorizationAcknowledged) errors.push('Autonomous pre-authorization requires explicit acknowledgement.');
  return errors;
}

export function authoritySummary(configuration: SessionConfiguration): string[] {
  const available = configuration.availableAgents.filter((agent) => configuration.availableAgentIds.includes(agent.id)).map((agent) => agent.label);
  const gates = configuration.requiredRoleRules.map((required) => `${required.role} (${required.applicability.replaceAll('_', ' ')})`);
  const noInterruption = configuration.approvalPolicy.behavior === 'preauthorize_session';
  return [
    `Coordinator is always available and may select: ${available.length ? available.join(', ') : 'no specialists'}.`,
    gates.length ? `Completion requires evidence from: ${gates.join(', ')}.` : 'No completion gates are required.',
    noInterruption ? `Pre-authorized until terminal result: ${configuration.approvalPolicy.preauthorizedCapabilities.join(', ') || 'no capabilities'} in ${configuration.preauthorizationScope || 'an unselected workspace'}. Pause and cancel remain reachable; non-bypassable safety denials still stop work.` : 'The app can pause, cancel, interrupt participants, and request policy approval while work is running.',
    `Workspace writes use ${configuration.workspaceMode.replace('_', ' ')} mode${configuration.workspaceMode === 'direct_write' ? '; rollback is limited and was explicitly acknowledged' : ''}; outside-workspace and destructive actions remain forbidden.`,
  ];
}
