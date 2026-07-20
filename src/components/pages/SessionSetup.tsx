import React, { useMemo, useState } from 'react';
import { useSettingsStore } from '@/stores/settingsStore';
import { useSessionStore } from '@/stores/sessionStore';
import { useUIStore } from '@/stores/uiStore';
import { useTauri } from '@/hooks/useTauri';
import { eventSimulator } from '@/services/eventSimulator';
import {
  applyPreset, authoritySummary, createConfiguration, limitDefinitions, markCustom,
  roleEvidence, validateConfiguration,
} from '@/services/sessionConfiguration';
import type { AgentInstance, ApprovalBehavior, ApprovalPolicy, ExecutionLimits, RequiredRoleRule, SessionConfiguration, SessionPreset, WorkspaceMode } from '@/types/session';
import './SessionSetup.css';

const capabilityOptions = ['workspace.read', 'workspace.write', 'test.run'];

function visibleAgentNames(configuration: SessionConfiguration): string {
  return configuration.availableAgents.filter((agent) => configuration.availableAgentIds.includes(agent.id)).map((agent) => agent.label).join(', ') || 'No specialists';
}

export const SessionSetup: React.FC = () => {
  const { defaultRoleModels } = useSettingsStore();
  const { createSession } = useSessionStore();
  const { setActivePage } = useUIStore();
  const { openDirectoryDialog } = useTauri();
  const [projectPath, setProjectPath] = useState('');
  const [goal, setGoal] = useState('');
  const [configuration, setConfiguration] = useState(() => createConfiguration(defaultRoleModels));

  const validation = useMemo(() => validateConfiguration(configuration), [configuration]);
  const canStart = projectPath.trim().length > 0 && goal.trim().length > 0 && validation.length === 0;
  const update = (change: (current: SessionConfiguration) => SessionConfiguration) => setConfiguration((current) => markCustom(change(current)));

  const handleSelectFolder = async () => {
    try {
      const path = await openDirectoryDialog();
      if (path) {
        setProjectPath(path);
        setConfiguration((current) => ({ ...current, preauthorizationScope: path, preauthorizationAcknowledged: false }));
      }
    } catch {
      // The native bridge exposes its error state separately; keep the form usable.
    }
  };

  const selectPreset = (preset: SessionPreset) => {
    if (preset === 'custom') return setConfiguration((current) => markCustom(current));
    setConfiguration((current) => applyPreset(current, preset));
  };

  const toggleAgent = (agent: AgentInstance) => update((current) => {
    const selected = current.availableAgentIds.includes(agent.id);
    const required = current.requiredRoleRules.some((rule) => rule.role === agent.role);
    if (selected && required) return current;
    return {
      ...current,
      availableAgentIds: selected ? current.availableAgentIds.filter((id) => id !== agent.id) : [...current.availableAgentIds, agent.id],
    };
  });

  const toggleRequiredRole = (agent: AgentInstance) => update((current) => {
    const matching = current.requiredRoleRules.find((rule) => rule.role === agent.role);
    if (matching) return { ...current, requiredRoleRules: current.requiredRoleRules.filter((rule) => rule.id !== matching.id) };
    const newRule: RequiredRoleRule = {
      id: `gate-${agent.role}`, role: agent.role, applicability: agent.role === 'reviewer' || agent.role === 'tester' ? 'when_changes' : 'always',
      successEvidence: roleEvidence(agent.role), minimumCompletions: 1,
    };
    return {
      ...current,
      availableAgentIds: current.availableAgentIds.includes(agent.id) ? current.availableAgentIds : [...current.availableAgentIds, agent.id],
      requiredRoleRules: [...current.requiredRoleRules, newRule],
    };
  });

  const updateRule = (role: AgentInstance['role'], change: (rule: RequiredRoleRule) => RequiredRoleRule) => update((current) => ({
    ...current, requiredRoleRules: current.requiredRoleRules.map((rule) => rule.role === role ? change(rule) : rule),
  }));

  const setLimit = (key: keyof ExecutionLimits, raw: string) => update((current) => ({
    ...current,
    executionLimits: { ...current.executionLimits, [key]: raw === '' ? null : Number(raw) },
  }));

  const setApprovalBehavior = (behavior: ApprovalBehavior) => update((current) => ({
    ...current,
    approvalPolicy: { ...current.approvalPolicy, behavior, preauthorizedCapabilities: behavior === 'preauthorize_session' ? current.approvalPolicy.preauthorizedCapabilities : [] },
    preauthorizationScope: behavior === 'preauthorize_session' ? current.preauthorizationScope || projectPath : '',
    preauthorizationAcknowledged: behavior === 'preauthorize_session' ? current.preauthorizationAcknowledged : false,
  }));

  const toggleCapability = (capability: string) => update((current) => {
    const selected = current.approvalPolicy.preauthorizedCapabilities.includes(capability);
    return {
      ...current,
      approvalPolicy: {
        ...current.approvalPolicy,
        preauthorizedCapabilities: selected
          ? current.approvalPolicy.preauthorizedCapabilities.filter((item) => item !== capability)
          : [...current.approvalPolicy.preauthorizedCapabilities, capability],
      },
      preauthorizationAcknowledged: false,
    };
  });

  const handleStart = () => {
    if (!canStart) return;
    const roleConfigs = [{ instanceId: 'coordinator', role: 'coordinator' as const, enabled: true, modelRef: configuration.coordinatorModel!, customSystemPrompt: configuration.coordinatorPromptOverride || undefined },
      ...configuration.availableAgents.filter((agent) => configuration.availableAgentIds.includes(agent.id)).map((agent) => ({ instanceId: agent.id, role: agent.role, enabled: true, modelRef: agent.modelRef!, }))];
    const sessionId = createSession({ projectPath, task: goal.trim(), roleConfigs, configuration });
    eventSimulator.start(sessionId, configuration);
    setActivePage('session');
  };

  return (
    <div className="session-setup">
      <div className="setup-inner">
        <header className="setup-header">
          <button className="setup-back-btn" onClick={() => setActivePage('dashboard')} aria-label="Back to dashboard">←</button>
          <div><h1 className="setup-title">New Session</h1><p className="setup-subtitle">Configure a visible, bounded Coordinator session.</p></div>
        </header>

        <nav className="preset-bar" aria-label="Session presets">
          {(['quick', 'balanced', 'thorough', 'custom'] as SessionPreset[]).map((preset) => (
            <button key={preset} type="button" className={`preset-button ${configuration.preset === preset ? 'preset-button--active' : ''}`} onClick={() => selectPreset(preset)} aria-pressed={configuration.preset === preset}>
              {preset[0].toUpperCase() + preset.slice(1)}
            </button>
          ))}
          <span className="preset-note">Resolved values remain visible below.</span>
        </nav>

        <div className="setup-grid">
          <section className="setup-card" aria-labelledby="setup-goal">
            <h2 id="setup-goal" className="setup-card-label">1 — Goal and workspace</h2>
            <label className="setup-label" htmlFor="project-path">Project workspace</label>
            <div className="setup-path-row"><input id="project-path" className="argus-input" value={projectPath} readOnly placeholder="Select a directory…" /><button type="button" className="setup-secondary-btn" onClick={handleSelectFolder}>Browse</button></div>
            <label className="setup-label" htmlFor="session-goal">Goal</label>
            <textarea id="session-goal" className="setup-textarea" value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="What should the team build or verify?" />
            <fieldset className="setup-fieldset"><legend>Workspace isolation</legend>{(['worktree', 'snapshot', 'direct_write'] as WorkspaceMode[]).map((mode) => <label key={mode} className="choice-row"><input type="radio" name="workspace-mode" checked={configuration.workspaceMode === mode} onChange={() => update((current) => ({ ...current, workspaceMode: mode, directWriteAcknowledged: mode === 'direct_write' ? false : current.directWriteAcknowledged }))} />{mode.replace('_', ' ')}</label>)}</fieldset>
            {configuration.workspaceMode === 'direct_write' && <div className="setup-warning"><strong>Direct write has limited rollback.</strong> Changes target the original project instead of an isolated worktree or snapshot.<label className="choice-row"><input type="checkbox" checked={configuration.directWriteAcknowledged} onChange={() => update((current) => ({ ...current, directWriteAcknowledged: !current.directWriteAcknowledged }))} />I understand that rollback is limited.</label></div>}
            <label className="setup-label" htmlFor="output-language">Output language</label><select id="output-language" className="setup-select" value={configuration.outputLanguage} onChange={(event) => update((current) => ({ ...current, outputLanguage: event.target.value as SessionConfiguration['outputLanguage'] }))}><option value="en">English</option><option value="tr">Türkçe</option></select>
          </section>

          <section className="setup-card" aria-labelledby="setup-coordinator">
            <h2 id="setup-coordinator" className="setup-card-label">2 — Coordinator</h2>
            <p className="setup-static">Coordinator is mandatory and receives messages without an @mention.</p>
            <label className="setup-label" htmlFor="coordinator-model">Model</label><select id="coordinator-model" className="setup-select" value={configuration.coordinatorModel ? 'configured' : 'missing'} onChange={(event) => update((current) => ({ ...current, coordinatorModel: event.target.value === 'missing' ? null : defaultRoleModels.coordinator ?? configuration.coordinatorModel }))}><option value="configured">{configuration.coordinatorModel?.displayName ?? 'Configured model'}</option><option value="missing">No model configured</option></select>
            <label className="setup-label" htmlFor="coordinator-prompt">Prompt override <span className="setup-muted">(optional)</span></label><textarea id="coordinator-prompt" className="setup-textarea setup-textarea--compact" value={configuration.coordinatorPromptOverride} onChange={(event) => update((current) => ({ ...current, coordinatorPromptOverride: event.target.value }))} placeholder="Keep routing and handoffs concise…" />
            <fieldset className="setup-fieldset"><legend>Enabled skills</legend><label className="choice-row"><input type="checkbox" checked={configuration.enabledSkills.includes('workspace-analysis')} onChange={() => update((current) => ({ ...current, enabledSkills: current.enabledSkills.includes('workspace-analysis') ? [] : ['workspace-analysis'] }))} />Workspace analysis</label></fieldset>
          </section>

          <section className="setup-card" aria-labelledby="setup-team">
            <h2 id="setup-team" className="setup-card-label">3 — Available team</h2><p className="setup-static">These are agent instances the Coordinator may select; roles are not a fixed pipeline.</p>
            <div className="agent-config-list">{configuration.availableAgents.map((agent) => { const selected = configuration.availableAgentIds.includes(agent.id); const required = configuration.requiredRoleRules.some((rule) => rule.role === agent.role); return <div className="agent-config-row" key={agent.id}><label><input type="checkbox" checked={selected} disabled={required} onChange={() => toggleAgent(agent)} /> <strong>{agent.label}</strong><span>{agent.modelRef?.displayName ?? 'Model missing'}</span></label><span className="agent-capabilities">{agent.capabilities.join(' · ')}</span>{required && <span className="required-lock">Required gate</span>}</div>; })}</div>
            <p className="setup-muted">Selected: {visibleAgentNames(configuration)}</p>
          </section>

          <section className="setup-card" aria-labelledby="setup-gates">
            <h2 id="setup-gates" className="setup-card-label">4 — Required roles</h2><p className="setup-static">A required role needs validated completion evidence before a successful result.</p>
            {configuration.availableAgents.map((agent) => { const required = configuration.requiredRoleRules.find((rule) => rule.role === agent.role); return <div key={agent.id} className="gate-row"><label className="choice-row"><input type="checkbox" checked={Boolean(required)} onChange={() => toggleRequiredRole(agent)} />Require {agent.label}</label>{required && <div className="gate-options"><label>Applies<select className="setup-select" value={required.applicability} onChange={(event) => updateRule(agent.role, (rule) => ({ ...rule, applicability: event.target.value as RequiredRoleRule['applicability'], capability: event.target.value === 'when_capability_used' ? 'workspace.write' : undefined }))}><option value="always">Always</option><option value="when_changes">When changes</option><option value="when_capability_used">When capability used</option></select></label>{required.applicability === 'when_capability_used' && <label>Capability<input className="argus-input" value={required.capability ?? ''} onChange={(event) => updateRule(agent.role, (rule) => ({ ...rule, capability: event.target.value }))} /></label>}<label>Evidence<input className="argus-input" value={required.successEvidence} onChange={(event) => updateRule(agent.role, (rule) => ({ ...rule, successEvidence: event.target.value }))} /></label></div>}</div>; })}
          </section>

          <section className="setup-card setup-card--wide" aria-labelledby="setup-limits">
            <h2 id="setup-limits" className="setup-card-label">5 — Limits</h2><p className="setup-static">Blank is unlimited user ceiling. 0 disables the named work; runtime safety guards still apply.</p>
            <div className="limits-grid">{limitDefinitions.map(({ key, label, unit, zeroMeaning }) => <label key={key} className="limit-field">{label}<input className="argus-input" type="number" min="0" step={key === 'maxSessionCost' ? '0.01' : '1'} value={configuration.executionLimits[key] ?? ''} onChange={(event) => setLimit(key, event.target.value)} /><span>{unit} · {zeroMeaning}</span></label>)}</div>
            <label className="limit-field">Soft warning ratio<input className="argus-input" type="number" min="0.01" max="1" step="0.01" value={configuration.executionLimits.softWarningRatio} onChange={(event) => update((current) => ({ ...current, executionLimits: { ...current.executionLimits, softWarningRatio: Number(event.target.value) } }))} /><span>fraction of each hard limit</span></label>
          </section>

          <section className="setup-card" aria-labelledby="setup-approvals">
            <h2 id="setup-approvals" className="setup-card-label">6 — Approvals</h2>
            <label className="setup-label" htmlFor="permission-profile">Permission profile</label><select id="permission-profile" className="setup-select" value={configuration.approvalPolicy.permissionProfile} onChange={(event) => update((current) => ({ ...current, approvalPolicy: { ...current.approvalPolicy, permissionProfile: event.target.value as ApprovalPolicy['permissionProfile'] }, preauthorizationAcknowledged: false }))}><option value="strict">Strict</option><option value="balanced">Balanced</option><option value="autonomous">Autonomous</option></select>
            <fieldset className="setup-fieldset"><legend>Approval behavior</legend>{(['ask_by_policy', 'preauthorize_session', 'deny_interactive'] as ApprovalBehavior[]).map((behavior) => <label key={behavior} className="choice-row"><input type="radio" name="approval-behavior" checked={configuration.approvalPolicy.behavior === behavior} onChange={() => setApprovalBehavior(behavior)} />{behavior === 'preauthorize_session' ? 'No-interruption mode (pre-authorize session)' : behavior.replaceAll('_', ' ')}</label>)}</fieldset>
            {configuration.approvalPolicy.behavior === 'preauthorize_session' && <fieldset className="setup-fieldset"><legend>Pre-authorized capabilities</legend><p className="setup-static">Exact workspace scope: <strong>{projectPath || 'Select a project workspace first'}</strong></p>{capabilityOptions.map((capability) => <label key={capability} className="choice-row"><input type="checkbox" checked={configuration.approvalPolicy.preauthorizedCapabilities.includes(capability)} onChange={() => toggleCapability(capability)} />{capability}</label>)}{configuration.approvalPolicy.permissionProfile === 'autonomous' && <label className="choice-row"><input type="checkbox" checked={configuration.preauthorizationAcknowledged} onChange={() => update((current) => ({ ...current, preauthorizationAcknowledged: !current.preauthorizationAcknowledged, preauthorizationScope: current.preauthorizationScope || projectPath }))} />I explicitly acknowledge these capabilities for this workspace.</label>}</fieldset>}
            <label className="setup-label" htmlFor="limit-resolution">At a hard limit</label><select id="limit-resolution" className="setup-select" value={configuration.approvalPolicy.limitResolution} onChange={(event) => update((current) => ({ ...current, approvalPolicy: { ...current.approvalPolicy, limitResolution: event.target.value as ApprovalPolicy['limitResolution'] } }))}><option value="ask_user">Ask user</option><option value="coordinator_decides">Coordinator decides</option><option value="stop">Stop</option></select>
          </section>

          <section className="setup-card" aria-labelledby="setup-review">
            <h2 id="setup-review" className="setup-card-label">7 — Review</h2>
            <ul className="review-summary">{authoritySummary(configuration).map((item) => <li key={item}>{item}</li>)}</ul>
            {validation.length > 0 && <div className="setup-validation" role="alert"><strong>Resolve before starting</strong><ul>{validation.map((error) => <li key={error}>{error}</li>)}</ul></div>}
            {!projectPath && <p className="setup-muted">Select a workspace to start.</p>}{!goal.trim() && <p className="setup-muted">Describe the goal to start.</p>}
            <button className="setup-init-btn" type="button" onClick={handleStart} disabled={!canStart}>Start Coordinator session</button>
          </section>
        </div>
      </div>
    </div>
  );
};
