import { expect, test } from 'vitest';
import {
  applyPreset, authoritySummary, createConfiguration, createReadOnlyAlphaConfiguration,
  enforceReadOnlyAlphaConfiguration, markCustom, READ_ONLY_ALPHA_TOOLS, validateConfiguration,
} from '@/services/sessionConfiguration';
import type { AgentRole, ModelRef } from '@/types/agent';

const configuredModel: ModelRef = { providerId: 'prv_configured', modelId: 'model-1', displayName: 'Configured model' };
const models = Object.fromEntries(['coordinator', 'planner', 'builder', 'reviewer', 'tester', 'ui_agent'].map((role) => [role, configuredModel])) as Record<AgentRole, ModelRef>;

test('a providerless configuration is rejected instead of receiving a synthetic model', () => {
  const configuration = createConfiguration({});
  expect(configuration.coordinatorModel).toBeNull();
  expect(configuration.availableAgents.every((agent) => agent.modelRef === null)).toBe(true);
  expect(validateConfiguration(configuration)).toEqual(expect.arrayContaining([
    'Coordinator requires a configured model.',
    'Builder requires a configured model.',
  ]));
});

test('Quick resolves to a Builder-only pool while keeping Coordinator mandatory outside the selectable pool', () => {
  const configuration = applyPreset(createConfiguration(models, 'custom'), 'quick');
  const selected = configuration.availableAgents.filter((agent) => configuration.availableAgentIds.includes(agent.id));
  expect(selected.map((agent) => agent.role)).toEqual(['builder']);
  expect(configuration.availableAgentIds).not.toContain('coordinator');
  expect(authoritySummary(configuration)[0]).toContain('Coordinator is always available');
});

test('Balanced resolves an automatic broad pool with Reviewer and Tester evidence gates', () => {
  const configuration = createConfiguration(models);
  expect(configuration.availableAgentIds).toHaveLength(5);
  expect(configuration.requiredRoleRules).toEqual(expect.arrayContaining([
    expect.objectContaining({ role: 'reviewer', successEvidence: 'approved_review' }),
    expect.objectContaining({ role: 'tester', successEvidence: 'passing_test_run' }),
  ]));
});

test('an invalid required role is rejected when no eligible instance is available', () => {
  const configuration = createConfiguration(models);
  const reviewer = configuration.availableAgents.find((agent) => agent.role === 'reviewer')!;
  const invalid = { ...configuration, availableAgentIds: configuration.availableAgentIds.filter((id) => id !== reviewer.id) };
  expect(validateConfiguration(invalid)).toContain('reviewer is required but no eligible instance is available.');
});

test('gates that cannot run under resolved limits or capabilities are rejected', () => {
  const configuration = createConfiguration(models);
  expect(validateConfiguration({ ...configuration, executionLimits: { ...configuration.executionLimits, maxAssignmentAttempts: 0 } })).toContain('Required role gates are incompatible with zero assignment attempts.');
  const tester = configuration.requiredRoleRules.find((rule) => rule.role === 'tester')!;
  const impossibleCapability = {
    ...configuration,
    requiredRoleRules: configuration.requiredRoleRules.map((rule) => rule.id === tester.id ? { ...rule, applicability: 'when_capability_used' as const, capability: 'network.admin' } : rule),
  };
  expect(validateConfiguration(impossibleCapability)).toContain('tester gate references a capability no available agent can use.');
  expect(validateConfiguration({ ...configuration, executionLimits: { ...configuration.executionLimits, maxModelIterationsPerAssignment: 0 } })).toContain('Required role gates are incompatible with zero model iterations.');
  expect(validateConfiguration({ ...configuration, executionLimits: { ...configuration.executionLimits, maxSessionTokens: 0 } })).toContain('Required role gates are incompatible with zero session tokens.');
  expect(validateConfiguration({ ...configuration, executionLimits: { ...configuration.executionLimits, maxWallClockSeconds: 0 } })).toContain('Required role gates are incompatible with zero wall-clock time.');
});

test('blank user ceilings and zero revisions have their distinct allowed semantics', () => {
  const configuration = createConfiguration(models, 'custom');
  const limits = { ...configuration.executionLimits, maxSessionTokens: null, maxRevisionsPerFinding: 0 };
  const validated = { ...configuration, executionLimits: limits };
  expect(validateConfiguration(validated)).toEqual([]);
});

test('no-interruption mode permits only profile-safe preauthorization and is plain-language visible', () => {
  const configuration = createConfiguration(models, 'custom');
  const enabled = {
    ...configuration,
    approvalPolicy: { ...configuration.approvalPolicy, permissionProfile: 'autonomous' as const, behavior: 'preauthorize_session' as const, preauthorizedCapabilities: ['workspace.read', 'test.run'] },
    preauthorizationScope: '/project',
    preauthorizationAcknowledged: true,
  };
  expect(validateConfiguration(enabled)).toEqual([]);
  expect(authoritySummary(enabled).join(' ')).toContain('Pre-authorized until terminal result');
  const unsafe = { ...enabled, approvalPolicy: { ...enabled.approvalPolicy, permissionProfile: 'balanced' as const, preauthorizedCapabilities: ['workspace.write'] } };
  expect(validateConfiguration(unsafe)).toContain('The selected permission profile cannot safely pre-authorize one or more capabilities.');
});

test('pre-authorization requires scope and explicit Autonomous acknowledgement, direct write requires limited-rollback acknowledgement, and evidence is registered', () => {
  const configuration = createConfiguration(models, 'custom');
  const preauthorized = { ...configuration, approvalPolicy: { ...configuration.approvalPolicy, permissionProfile: 'autonomous' as const, behavior: 'preauthorize_session' as const, preauthorizedCapabilities: ['workspace.read'] } };
  expect(validateConfiguration(preauthorized)).toEqual(expect.arrayContaining(['Pre-authorized work requires an exact workspace scope.', 'Autonomous pre-authorization requires explicit acknowledgement.']));
  expect(validateConfiguration({ ...configuration, workspaceMode: 'direct_write' })).toContain('Direct-write mode requires acknowledgement that rollback is limited.');
  const withGate = createConfiguration(models);
  const unsupportedEvidence = { ...withGate, requiredRoleRules: [{ ...withGate.requiredRoleRules[0]!, successEvidence: 'made_up_evidence' }] };
  expect(validateConfiguration(unsupportedEvidence)).toContain('reviewer uses an unsupported success evidence type.');
});

test('selected specialist models and decimal cost are validated with their real units', () => {
  const configuration = createConfiguration(models, 'custom');
  const builder = configuration.availableAgents.find((agent) => agent.role === 'builder')!;
  const missingModel = { ...configuration, availableAgents: configuration.availableAgents.map((agent) => agent.id === builder.id ? { ...agent, modelRef: null } : agent) };
  expect(validateConfiguration(missingModel)).toContain('Builder requires a configured model.');
  expect(validateConfiguration({ ...configuration, executionLimits: { ...configuration.executionLimits, maxSessionCost: 2.75 } })).toEqual([]);
});

test('editing a resolved preset transitions it to Custom without hiding its values', () => {
  const balanced = createConfiguration(models, 'balanced');
  const custom = markCustom({ ...balanced, executionLimits: { ...balanced.executionLimits, maxToolCallsPerAssignment: 5 } });
  expect(custom.preset).toBe('custom');
  expect(custom.executionLimits.maxToolCallsPerAssignment).toBe(5);
});

test('the Alpha normalizer strips every unsupported authority from a broad future configuration', () => {
  const broad = createConfiguration(models, 'thorough');
  const normalized = enforceReadOnlyAlphaConfiguration({
    ...broad,
    workspaceMode: 'direct_write',
    directWriteAcknowledged: true,
    preauthorizationAcknowledged: true,
    preauthorizationScope: '/project',
    enabledSkills: ['write-skill'],
    approvalPolicy: {
      permissionProfile: 'expert_unrestricted', behavior: 'preauthorize_session',
      preauthorizedCapabilities: ['workspace.write'], capabilityOverrides: { 'workspace.write': 'allow' }, limitResolution: 'ask_user',
    },
  });

  expect(normalized).toMatchObject({
    preset: 'custom', workspaceMode: 'worktree', directWriteAcknowledged: false,
    preauthorizationAcknowledged: false, preauthorizationScope: '', enabledSkills: [], requiredRoleRules: [],
    executionLimits: { maxParallelReadOnlyAssignments: 1, maxRevisionsPerFinding: 0 },
    approvalPolicy: { permissionProfile: 'balanced', behavior: 'ask_by_policy', preauthorizedCapabilities: [], capabilityOverrides: {}, limitResolution: 'stop' },
  });
  expect(normalized.availableAgents.every((agent) => agent.permissionProfile === 'balanced')).toBe(true);
  expect(normalized.availableAgents.every((agent) => agent.capabilities.every((capability) => capability === 'workspace.read'))).toBe(true);
  expect(normalized.availableAgents.every((agent) => agent.toolAllowlist.every((tool) => (READ_ONLY_ALPHA_TOOLS as readonly string[]).includes(tool)))).toBe(true);
});

test('the Alpha normalizer preserves stricter authority instead of silently widening it', () => {
  const configuration = createConfiguration(models, 'custom');
  const normalized = enforceReadOnlyAlphaConfiguration({
    ...configuration,
    coordinatorPermissionProfile: 'strict',
    availableAgents: configuration.availableAgents.map((agent) => ({ ...agent, permissionProfile: 'strict' })),
    approvalPolicy: { ...configuration.approvalPolicy, permissionProfile: 'strict' },
  });
  expect(normalized.coordinatorPermissionProfile).toBe('strict');
  expect(normalized.availableAgents.every((agent) => agent.permissionProfile === 'strict')).toBe(true);
  expect(normalized.approvalPolicy.permissionProfile).toBe('strict');
});

test('read-only Alpha prefers Planner, falls back deterministically, and fails closed without an eligible model', () => {
  expect(createReadOnlyAlphaConfiguration(models).availableAgentIds).toEqual(['builtin-planner']);
  expect(createReadOnlyAlphaConfiguration({ coordinator: configuredModel, reviewer: configuredModel, builder: configuredModel }).availableAgentIds).toEqual(['builtin-builder']);
  expect(createReadOnlyAlphaConfiguration({ coordinator: configuredModel }).availableAgentIds).toEqual([]);
});
