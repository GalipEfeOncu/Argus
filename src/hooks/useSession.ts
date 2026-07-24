import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSessionStore } from '@/stores/sessionStore';
import { useAgentStore } from '@/stores/agentStore';
import { api } from '@/services/api';
import type { SessionConfig } from '@/types/session';
import type { AgentInfo } from '@/types/agent';
import type { components } from '@/types/generated/rest';

export function useSession() {
  const navigate = useNavigate();
  const sessionStore = useSessionStore();
  const agentStore = useAgentStore();

  const startSession = useCallback(async (config: SessionConfig) => {
    // Create session in backend
    const response = await api.sessions.create(toSessionCreateRequest(config));
    const { id } = response;
    const normalized = normalizeSessionConfig(config, response);
    
    // Create in local store
    sessionStore.createSession(normalized, id);
    sessionStore.setActiveSession(id);

    // Initialize agents
    const agentInfos: AgentInfo[] = normalized.roleConfigs
      .filter((rc) => rc.enabled)
      .map((rc) => ({
        instanceId: rc.instanceId,
        role: rc.role,
        status: 'idle',
        modelRef: rc.modelRef,
        tokenCount: 0,
      }));
    agentStore.initAgents(agentInfos);

    navigate(`/session/${id}`);
  }, [navigate, sessionStore, agentStore]);

  const stopSession = useCallback((id: string) => {
    sessionStore.updateSessionStatus(id, 'completed');
    agentStore.clearSession();
  }, [sessionStore, agentStore]);

  return { startSession, stopSession };
}

type SessionCreateResponse = Awaited<ReturnType<typeof api.sessions.create>>;

function normalizeSessionConfig(config: SessionConfig, response: SessionCreateResponse): SessionConfig {
  const snapshotIdBySource = new Map(response.agentSnapshots.map((snapshot) => [snapshot.sourceAgentId, snapshot.id]));
  const normalizeId = (id: string) => snapshotIdBySource.get(id) ?? id;
  const serverValue = <Value,>(value: Value | undefined, fallback: Value): Value => value === undefined ? fallback : value;
  return {
    ...config,
    roleConfigs: config.roleConfigs.map((roleConfig) => ({
      ...roleConfig,
      instanceId: normalizeId(roleConfig.instanceId ?? `builtin_${roleConfig.role}`),
    })),
    configuration: {
      ...config.configuration,
      availableAgents: config.configuration.availableAgents.map((agent) => ({ ...agent, id: normalizeId(agent.id) })),
      availableAgentIds: response.availableAgentIds,
      requiredRoleRules: config.configuration.requiredRoleRules,
      executionLimits: {
        ...config.configuration.executionLimits,
        maxRevisionsPerFinding: serverValue(response.executionLimits.maxRevisionsPerFinding, config.configuration.executionLimits.maxRevisionsPerFinding),
        maxAssignmentAttempts: serverValue(response.executionLimits.maxAssignmentAttempts, config.configuration.executionLimits.maxAssignmentAttempts),
        maxModelIterationsPerAssignment: serverValue(response.executionLimits.maxModelIterationsPerAssignment, config.configuration.executionLimits.maxModelIterationsPerAssignment),
        maxToolCallsPerAssignment: serverValue(response.executionLimits.maxToolCallsPerAssignment, config.configuration.executionLimits.maxToolCallsPerAssignment),
        maxSessionTokens: serverValue(response.executionLimits.maxSessionTokens, config.configuration.executionLimits.maxSessionTokens),
        maxSessionCost: serverValue(response.executionLimits.maxSessionCost, config.configuration.executionLimits.maxSessionCost),
        maxWallClockSeconds: serverValue(response.executionLimits.maxWallClockSeconds, config.configuration.executionLimits.maxWallClockSeconds),
        maxParallelReadOnlyAssignments: serverValue(response.executionLimits.maxParallelReadOnlyAssignments, config.configuration.executionLimits.maxParallelReadOnlyAssignments),
        softWarningRatio: serverValue(response.executionLimits.softWarningRatio, config.configuration.executionLimits.softWarningRatio),
      },
      approvalPolicy: {
        ...config.configuration.approvalPolicy,
        ...response.approvalPolicy,
        preauthorizedCapabilities: serverValue(response.approvalPolicy.preauthorizedCapabilities, config.configuration.approvalPolicy.preauthorizedCapabilities),
      },
      workspaceMode: response.workspacePolicy.mode ?? config.configuration.workspaceMode,
      directWriteAcknowledged: response.acknowledgements.includes('direct_write_limited_rollback'),
      preauthorizationAcknowledged: response.acknowledgements.includes('autonomous_permissions'),
    },
  };
}

function toSessionCreateRequest(config: SessionConfig): components['schemas']['SessionCreateRequest'] {
  const capabilitiesById = new Map(config.configuration.availableAgents.map((agent) => [agent.id, agent.capabilities]));
  const agents = config.roleConfigs.filter((roleConfig) => roleConfig.enabled).map((roleConfig) => {
    const id = roleConfig.instanceId ?? `builtin_${roleConfig.role}`;
    return {
      id,
      role: roleConfig.role,
      capabilities: capabilitiesById.get(id) ?? [],
      modelSnapshot: { providerId: roleConfig.modelRef.providerId, modelId: roleConfig.modelRef.modelId },
    };
  });
  const coordinatorAgentId = agents.find((agent) => agent.role === 'coordinator')?.id ?? 'coordinator';
  const acknowledgements = [
    ...(config.configuration.directWriteAcknowledged ? ['direct_write_limited_rollback'] : []),
    ...(config.configuration.preauthorizationAcknowledged && config.configuration.approvalPolicy.permissionProfile === 'autonomous' ? ['autonomous_permissions'] : []),
  ];
  return {
    projectPath: config.projectPath,
    task: config.task,
    ...(config.name === undefined ? {} : { name: config.name }),
    coordinatorAgentId,
    agents,
    roleConfigs: config.roleConfigs.map((roleConfig) => ({
      role: roleConfig.role, enabled: roleConfig.enabled, providerId: roleConfig.modelRef.providerId,
      modelId: roleConfig.modelRef.modelId,
      ...(roleConfig.customSystemPrompt === undefined ? {} : { customSystemPrompt: roleConfig.customSystemPrompt }),
    })),
    configuration: {
      availableAgentIds: config.configuration.availableAgentIds,
      requiredRoleRules: config.configuration.requiredRoleRules,
      executionLimits: config.configuration.executionLimits,
      approvalPolicy: config.configuration.approvalPolicy,
      workspacePolicy: { mode: config.configuration.workspaceMode },
      acknowledgements,
    },
    workspaceMode: config.configuration.workspaceMode,
    acknowledgeDirectWrite: config.configuration.directWriteAcknowledged,
  };
}
