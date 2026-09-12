import React, { useEffect, useMemo, useState } from 'react';
import { useSettingsStore } from '@/stores/settingsStore';
import { useSessionStore } from '@/stores/sessionStore';
import { useAgentStore } from '@/stores/agentStore';
import { useUIStore } from '@/stores/uiStore';
import { useWorkspaceStore } from '@/stores/workspaceStore';
import { useTauri } from '@/hooks/useTauri';
import { api } from '@/services/api';
import { tauriCommands } from '@/services/tauri';
import {
  createReadOnlyAlphaConfiguration, enforceReadOnlyAlphaConfiguration, limitDefinitions,
  markCustom, readOnlyAlphaAuthoritySummary, READ_ONLY_ALPHA_TOOLS, validateConfiguration,
} from '@/services/sessionConfiguration';
import type { AgentInstance, ExecutionLimits, SessionConfiguration } from '@/types/session';
import type { AgentInfo, AgentRole, ModelRef } from '@/types/agent';
import './SessionSetup.css';

const readOnlyLimitDefinitions = limitDefinitions.filter(({ key }) => !['maxRevisionsPerFinding', 'maxParallelReadOnlyAssignments'].includes(key));

function visibleAgentNames(configuration: SessionConfiguration): string {
  return configuration.availableAgents.filter((agent) => configuration.availableAgentIds.includes(agent.id)).map((agent) => agent.label).join(', ') || 'No specialists';
}

function toSessionCreateRequest(
  projectPath: string,
  goal: string,
  configuration: SessionConfiguration,
): Parameters<typeof api.sessions.create>[0] {
  const runtimeConfiguration = enforceReadOnlyAlphaConfiguration(configuration);
  return {
    sessionType: 'project',
    projectPath,
    goal,
    coordinatorAgentId: 'coordinator',
    agents: [
      {
        id: 'coordinator', role: 'coordinator', agentDefinitionId: runtimeConfiguration.coordinatorDefinitionId,
        modelBinding: runtimeConfiguration.coordinatorModel === null ? undefined : {
          providerProfileId: runtimeConfiguration.coordinatorModel.providerId, modelId: runtimeConfiguration.coordinatorModel.modelId,
        },
        permissionProfile: runtimeConfiguration.coordinatorPermissionProfile,
        skillIds: runtimeConfiguration.enabledSkills,
        ...(runtimeConfiguration.coordinatorPromptOverride.trim() ? { systemPrompt: runtimeConfiguration.coordinatorPromptOverride } : {}),
        outputLanguage: runtimeConfiguration.outputLanguage,
      },
      ...runtimeConfiguration.availableAgents.map((agent) => ({
        id: agent.id, role: agent.role, agentDefinitionId: agent.agentDefinitionId, capabilities: agent.capabilities,
        ...(agent.modelRef === null ? {} : { modelBinding: { providerProfileId: agent.modelRef.providerId, modelId: agent.modelRef.modelId } }),
        permissionProfile: agent.permissionProfile,
        outputLanguage: runtimeConfiguration.outputLanguage,
      })),
    ],
    configuration: {
      availableAgentIds: runtimeConfiguration.availableAgentIds,
      requiredRoleRules: runtimeConfiguration.requiredRoleRules.map((rule) => ({
        id: rule.id,
        role: rule.role,
        applicability: rule.applicability,
        successEvidence: rule.successEvidence,
        minimumCompletions: rule.minimumCompletions,
        requiredCapabilities: [],
        ...(rule.capability === undefined ? {} : { capability: rule.capability }),
      })),
      executionLimits: runtimeConfiguration.executionLimits,
      approvalPolicy: runtimeConfiguration.approvalPolicy,
      workspacePolicy: { mode: runtimeConfiguration.workspaceMode },
      acknowledgements: [],
    },
    workspaceMode: runtimeConfiguration.workspaceMode,
    acknowledgeDirectWrite: false,
  };
}

function liveAgentInfos(
  configuration: SessionConfiguration,
  snapshots: Array<{ id: string; sourceAgentId: string; role: string }>,
): AgentInfo[] {
  return snapshots.map((snapshot) => {
    const source = configuration.availableAgents.find((agent) => agent.id === snapshot.sourceAgentId);
    const modelRef = snapshot.sourceAgentId === 'coordinator' ? configuration.coordinatorModel : source?.modelRef;
    if (modelRef === null || modelRef === undefined) throw new Error(`Missing configured model for ${snapshot.sourceAgentId}.`);
    return {
      instanceId: snapshot.id,
      label: source?.label ?? (snapshot.role === 'coordinator' ? 'Coordinator' : snapshot.role),
      role: snapshot.role as AgentRole,
      status: 'idle',
      modelRef,
      tokenCount: 0,
    };
  });
}

export const SessionSetup: React.FC = () => {
  const { defaultRoleModels, manualProviderModels } = useSettingsStore();
  const { createSession } = useSessionStore();
  const { initAgents } = useAgentStore();
  const { setActivePage } = useUIStore();
  const invalidateWorkspaceCatalog = useWorkspaceStore((state) => state.invalidate);
  const { openDirectoryDialog } = useTauri();
  const [projectPath, setProjectPath] = useState('');
  const [goal, setGoal] = useState('');
  const [configuration, setConfiguration] = useState(() => createReadOnlyAlphaConfiguration(defaultRoleModels));
  const [startError, setStartError] = useState<string | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [coordinatorDefinitions, setCoordinatorDefinitions] = useState<Array<{ id: string; name: string; permissionProfile: SessionConfiguration['coordinatorPermissionProfile'] }>>([
    { id: 'builtin.coordinator.v1', name: 'Coordinator', permissionProfile: 'balanced' },
  ]);
  const [providerModels, setProviderModels] = useState<ModelRef[]>([]);
  const [modelsLoaded, setModelsLoaded] = useState(false);
  const [providerCatalogState, setProviderCatalogState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [providerReload, setProviderReload] = useState(0);
  const [definitionCatalogState, setDefinitionCatalogState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [definitionReload, setDefinitionReload] = useState(0);

  useEffect(() => {
    let active = true;
    setProviderCatalogState('loading');
    setModelsLoaded(false);
    const providerApi = api.providers;
    if (providerApi === undefined) return () => { active = false; };
    void providerApi.list().then(async (profiles) => {
      await Promise.all(profiles.filter((profile) => profile.credentialConfigured).map((profile) => tauriCommands.refreshProviderCredential(profile.id).catch(() => undefined)));
      const listed = await Promise.allSettled(profiles.map(async (profile) => ({ profile, response: await providerApi.listModels(profile.id) })));
      if (!active) return;
      const profileIds = new Set(profiles.map((profile) => profile.id));
      const discovered = listed.flatMap((result) => result.status === 'fulfilled'
        ? result.value.response.models.map((model) => ({ providerId: result.value.profile.id, modelId: model.id, displayName: `${result.value.profile.displayName} · ${model.displayName}${model.supportsStructuredOutput === false ? ' · structured output unavailable' : ''}` }))
        : []);
      setProviderModels([...discovered, ...manualProviderModels.filter((model) => profileIds.has(model.providerId))]);
      setModelsLoaded(true);
      setProviderCatalogState(listed.some((result) => result.status === 'rejected') ? 'error' : 'ready');
    }).catch(() => { if (active) { setProviderModels([]); setModelsLoaded(true); setProviderCatalogState('error'); } });
    return () => { active = false; };
  }, [manualProviderModels, providerReload]);

  useEffect(() => {
    let active = true;
    setDefinitionCatalogState('loading');
    const listDefinitions = api.agentDefinitions?.list;
    if (listDefinitions === undefined) return () => { active = false; };
    void listDefinitions().then((definitions) => {
      if (!active) return;
      const customAgents: AgentInstance[] = definitions
        .filter((definition) => definition.kind !== 'builtin' && definition.role !== 'coordinator')
        .map((definition) => ({
          id: `definition-${definition.id}`,
          role: definition.role,
          label: definition.name,
          modelRef: { providerId: definition.modelBinding.providerProfileId, modelId: definition.modelBinding.modelId, displayName: definition.modelBinding.modelId },
          capabilities: definition.capabilities ?? [],
          agentDefinitionId: definition.id,
          evidenceKinds: definition.evidenceKinds ?? [],
          toolAllowlist: definition.toolAllowlist ?? [],
          permissionProfile: definition.permissionProfile,
          outputLanguage: definition.outputLanguage,
        }));
      setConfiguration((current) => enforceReadOnlyAlphaConfiguration({
        ...current,
        availableAgents: [...current.availableAgents.filter((agent) => !agent.id.startsWith('definition-')), ...customAgents],
      }));
      setCoordinatorDefinitions([
        { id: 'builtin.coordinator.v1', name: 'Coordinator', permissionProfile: 'balanced' },
        ...definitions.filter((definition) => definition.role === 'coordinator' && definition.id !== 'builtin.coordinator.v1')
          .map((definition) => ({ id: definition.id, name: definition.name, permissionProfile: definition.permissionProfile })),
      ]);
      setDefinitionCatalogState('ready');
    }).catch(() => { if (active) setDefinitionCatalogState('error'); });
    return () => { active = false; };
  }, [definitionReload]);

  const validation = useMemo(() => {
    const runtimeConfiguration = enforceReadOnlyAlphaConfiguration(configuration);
    const errors = validateConfiguration(runtimeConfiguration);
    const availableModels = new Set(providerModels.map((model) => `${model.providerId}:${model.modelId}`));
    const selectedModels = [runtimeConfiguration.coordinatorModel, ...runtimeConfiguration.availableAgents.filter((agent) => runtimeConfiguration.availableAgentIds.includes(agent.id)).map((agent) => agent.modelRef)];
    if (modelsLoaded && selectedModels.some((model) => model !== null && !availableModels.has(`${model.providerId}:${model.modelId}`))) {
      errors.push('Every selected model must belong to a configured provider profile and its available model list.');
    }
    if (runtimeConfiguration.availableAgentIds.length === 0) errors.push('A configured read-only specialist model is required.');
    return errors;
  }, [configuration, modelsLoaded, providerModels]);
  const canStart = providerCatalogState === 'ready' && modelsLoaded && projectPath.trim().length > 0 && goal.trim().length > 0 && validation.length === 0;
  const update = (change: (current: SessionConfiguration) => SessionConfiguration) => setConfiguration((current) => markCustom(change(current)));

  const handleSelectFolder = async () => {
    try {
      const path = await openDirectoryDialog();
      if (path) {
        setProjectPath(path);
      }
    } catch {
      // The native bridge exposes its error state separately; keep the form usable.
    }
  };

  const toggleAgent = (agent: AgentInstance) => update((current) => {
    const selected = current.availableAgentIds.includes(agent.id);
    return {
      ...current,
      availableAgentIds: selected ? current.availableAgentIds.filter((id) => id !== agent.id) : [...current.availableAgentIds, agent.id],
    };
  });

  const setLimit = (key: keyof ExecutionLimits, raw: string) => update((current) => ({
    ...current,
    executionLimits: { ...current.executionLimits, [key]: raw === '' ? null : Number(raw) },
  }));

  const handleStart = async () => {
    if (!canStart) return;
    setStartError(null);
    setIsStarting(true);
    const runtimeConfiguration = enforceReadOnlyAlphaConfiguration(configuration);
    const roleConfigs = [{ instanceId: 'coordinator', role: 'coordinator' as const, enabled: true, modelRef: runtimeConfiguration.coordinatorModel!, customSystemPrompt: runtimeConfiguration.coordinatorPromptOverride || undefined },
      ...runtimeConfiguration.availableAgents.filter((agent) => runtimeConfiguration.availableAgentIds.includes(agent.id)).map((agent) => ({ instanceId: agent.id, role: agent.role, enabled: true, modelRef: agent.modelRef!, }))];
    try {
      const configuredProfileIds = new Set(providerModels.map((model) => model.providerId));
      const profileIds = new Set([runtimeConfiguration.coordinatorModel, ...runtimeConfiguration.availableAgents.filter((agent) => runtimeConfiguration.availableAgentIds.includes(agent.id)).map((agent) => agent.modelRef)].flatMap((model) => model !== null && configuredProfileIds.has(model.providerId) ? [model.providerId] : []));
      await Promise.all([...profileIds].map((profileId) => tauriCommands.refreshProviderCredential(profileId)));
      const created = await api.sessions.create(toSessionCreateRequest(projectPath, goal.trim(), runtimeConfiguration));
      // The local store only retains render metadata.  The canonical snapshot
      // and every timeline entry arrive through the live transport.
      initAgents(liveAgentInfos(runtimeConfiguration, created.agentSnapshots));
      createSession({ projectPath, task: goal.trim(), roleConfigs, configuration: runtimeConfiguration }, created.id);
      invalidateWorkspaceCatalog();
      setActivePage('session');
    } catch {
      setStartError('The local runtime could not create this isolated session. Check that the backend is running and try again.');
    } finally {
      setIsStarting(false);
    }
  };

  return (
    <div className="session-setup">
      <div className="setup-inner">
        <header className="setup-header">
          <button type="button" className="setup-back-btn" onClick={() => setActivePage('dashboard')} aria-label="Back to dashboard">←</button>
        <div><h1 className="setup-title">New Project Session</h1><p className="setup-subtitle">Configure a bounded workspace inspection with a visible Coordinator.</p></div>
        </header>

        <div className="setup-runtime-scope" role="note"><strong>Read-only Alpha runtime</strong><span>Coordinator may dispatch at most one specialist per turn. Specialists can only inspect with {READ_ONLY_ALPHA_TOOLS.join(', ')} when their immutable definition allows the requested tool. No files are changed and no tests or shell commands run.</span></div>

        <div className="setup-grid">
          <section className="setup-card" aria-labelledby="setup-goal">
            <h2 id="setup-goal" className="setup-card-label">1 — Inspection goal and workspace</h2>
            <label className="setup-label" htmlFor="project-path">Project workspace</label>
            <div className="setup-path-row"><input id="project-path" className="argus-input" value={projectPath} readOnly placeholder="Select a directory…" /><button type="button" className="setup-secondary-btn" onClick={handleSelectFolder}>Browse</button></div>
            <label className="setup-label" htmlFor="session-goal">Goal</label>
            <textarea id="session-goal" className="setup-textarea" value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="What should Coordinator inspect or analyze?" />
            <p className="setup-static"><strong>Workspace access:</strong> isolated, read-only inspection. Direct-write and mutation modes are not available in this Alpha.</p>
            <label className="setup-label" htmlFor="output-language">Output language</label><select id="output-language" className="setup-select" value={configuration.outputLanguage} onChange={(event) => update((current) => ({ ...current, outputLanguage: event.target.value as SessionConfiguration['outputLanguage'] }))}><option value="en">English</option><option value="tr">Türkçe</option></select>
          </section>

          <section className="setup-card" aria-labelledby="setup-coordinator">
            <h2 id="setup-coordinator" className="setup-card-label">2 — Coordinator</h2>
            <p className="setup-static">Coordinator is mandatory and receives messages without an @mention.</p>
            {definitionCatalogState === 'loading' && <p className="setup-muted" role="status">Loading agent definitions…</p>}
            {definitionCatalogState === 'error' && <div className="setup-catalog-error" role="alert"><span>Agent definitions could not be loaded. Built-in definitions remain available.</span><button type="button" className="setup-secondary-btn" onClick={() => setDefinitionReload((value) => value + 1)}>Retry definitions</button></div>}
            {providerCatalogState === 'loading' && <p className="setup-muted" role="status">Loading configured provider models…</p>}
            {providerCatalogState === 'error' && <div className="setup-catalog-error" role="alert"><span>Configured provider models could not be loaded. Session start is disabled until the local catalogue is available.</span><button type="button" className="setup-secondary-btn" onClick={() => setProviderReload((value) => value + 1)}>Retry provider models</button></div>}
            <label className="setup-label" htmlFor="coordinator-definition">Definition version</label><select id="coordinator-definition" className="setup-select" value={configuration.coordinatorDefinitionId} onChange={(event) => { const definition = coordinatorDefinitions.find((item) => item.id === event.target.value); update((current) => ({ ...current, coordinatorDefinitionId: event.target.value, coordinatorPermissionProfile: definition?.permissionProfile ?? current.coordinatorPermissionProfile })); }}>{coordinatorDefinitions.map((definition) => <option key={definition.id} value={definition.id}>{definition.name}</option>)}</select>
            <label className="setup-label" htmlFor="coordinator-model">Model</label><select id="coordinator-model" className="setup-select" value={configuration.coordinatorModel ? `${configuration.coordinatorModel.providerId}:${configuration.coordinatorModel.modelId}` : 'missing'} onChange={(event) => { const selected = providerModels.find((model) => `${model.providerId}:${model.modelId}` === event.target.value); update((current) => ({ ...current, coordinatorModel: event.target.value === 'missing' ? null : selected ?? defaultRoleModels.coordinator ?? current.coordinatorModel })); }}><option value="missing">No model configured</option>{configuration.coordinatorModel && !providerModels.some((model) => model.providerId === configuration.coordinatorModel?.providerId && model.modelId === configuration.coordinatorModel.modelId) && <option value={`${configuration.coordinatorModel.providerId}:${configuration.coordinatorModel.modelId}`}>{configuration.coordinatorModel.displayName}</option>}{providerModels.map((model) => <option key={`${model.providerId}:${model.modelId}`} value={`${model.providerId}:${model.modelId}`}>{model.displayName}</option>)}</select>
            <label className="setup-label" htmlFor="coordinator-prompt">Prompt override <span className="setup-muted">(optional)</span></label><textarea id="coordinator-prompt" className="setup-textarea setup-textarea--compact" value={configuration.coordinatorPromptOverride} onChange={(event) => update((current) => ({ ...current, coordinatorPromptOverride: event.target.value }))} placeholder="Keep routing and handoffs concise…" />
            <p className="setup-muted">Coordinator receives no workspace tools. It routes one bounded read-only specialist assignment, then receives the specialist’s redacted result.</p>
          </section>

          <section className="setup-card setup-card--team" aria-labelledby="setup-team">
            <h2 id="setup-team" className="setup-card-label">3 — Read-only specialist pool</h2><p className="setup-static">Coordinator may choose one selected specialist per turn. Role names do not grant build, write, test, or shell authority in this runtime.</p>
            <div className="agent-config-list">{configuration.availableAgents.filter((agent) => agent.capabilities.includes('workspace.read')).map((agent) => { const selected = configuration.availableAgentIds.includes(agent.id); const modelValue = agent.modelRef === null ? 'missing' : `${agent.modelRef.providerId}:${agent.modelRef.modelId}`; return <div className="agent-config-row" key={agent.id}><label><input type="checkbox" checked={selected} onChange={() => toggleAgent(agent)} /> <strong>{agent.label}</strong> — inspection only</label><label className="setup-label" htmlFor={`agent-model-${agent.id}`}>Model<select id={`agent-model-${agent.id}`} className="setup-select" value={modelValue} disabled={!selected} onChange={(event) => { const model = providerModels.find((item) => `${item.providerId}:${item.modelId}` === event.target.value) ?? null; update((current) => ({ ...current, availableAgents: current.availableAgents.map((item) => item.id === agent.id ? { ...item, modelRef: model } : item) })); }}><option value="missing">No model configured</option>{agent.modelRef !== null && !providerModels.some((model) => model.providerId === agent.modelRef?.providerId && model.modelId === agent.modelRef.modelId) && <option value={modelValue}>{agent.modelRef.displayName}</option>}{providerModels.map((model) => <option key={`${model.providerId}:${model.modelId}`} value={`${model.providerId}:${model.modelId}`}>{model.displayName}</option>)}</select></label><span className="agent-capabilities">workspace.read · allowed tools are intersected with {READ_ONLY_ALPHA_TOOLS.join(', ')}</span>{agent.agentDefinitionId.startsWith('builtin.') ? null : <span className="setup-muted">Custom definition</span>}</div>; })}</div>
            <p className="setup-muted">Selected: {visibleAgentNames(configuration)}</p>
          </section>

          <section className="setup-card setup-card--limits" aria-labelledby="setup-limits">
            <h2 id="setup-limits" className="setup-card-label">4 — Read-only execution limits</h2><p className="setup-static">Blank is unlimited user ceiling. The worker still caps each read-only assignment to its production safety maximums; parallel work is fixed to one.</p>
            <div className="limits-grid">{readOnlyLimitDefinitions.map(({ key, label, unit, zeroMeaning }) => <label key={key} className="limit-field">{label}<input className="argus-input" type="number" min="0" step={key === 'maxSessionCost' ? '0.01' : '1'} value={configuration.executionLimits[key] ?? ''} onChange={(event) => setLimit(key, event.target.value)} /><span>{unit} · {zeroMeaning}</span></label>)}</div>
            <label className="limit-field">Soft warning ratio<input className="argus-input" type="number" min="0.01" max="1" step="0.01" value={configuration.executionLimits.softWarningRatio} onChange={(event) => update((current) => ({ ...current, executionLimits: { ...current.executionLimits, softWarningRatio: Number(event.target.value) } }))} /><span>fraction of each hard limit</span></label>
          </section>

          <section className="setup-card setup-card--review" aria-labelledby="setup-review">
            <h2 id="setup-review" className="setup-card-label">5 — Review read-only authority</h2>
            <ul className="review-summary">{readOnlyAlphaAuthoritySummary(enforceReadOnlyAlphaConfiguration(configuration)).map((item) => <li key={item}>{item}</li>)}</ul>
            {validation.length > 0 && <div className="setup-validation" role="alert"><strong>Resolve before starting</strong><ul>{validation.map((error) => <li key={error}>{error}</li>)}</ul></div>}
            {!modelsLoaded && providerCatalogState !== 'error' && <p className="setup-muted">Loading configured provider models…</p>}
            {!projectPath && <p className="setup-muted">Select a workspace to start.</p>}{!goal.trim() && <p className="setup-muted">Describe the goal to start.</p>}
            {startError !== null && <p className="setup-validation" role="alert">{startError}</p>}
            <button className="setup-init-btn" type="button" onClick={() => void handleStart()} disabled={!canStart || isStarting}>{isStarting ? 'Creating read-only session…' : 'Start read-only Coordinator session'}</button>
          </section>
        </div>
      </div>
    </div>
  );
};
