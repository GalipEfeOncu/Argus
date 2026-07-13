import React, { useState } from 'react';
import { useSettingsStore } from '@/stores/settingsStore';
import { useSessionStore } from '@/stores/sessionStore';
import { useUIStore } from '@/stores/uiStore';
import { useTauri } from '@/hooks/useTauri';
import { AGENT_ROLE_META } from '@/types/agent';
import type { AgentRole } from '@/types/agent';
import './SessionSetup.css';

const roleIconColors: Record<AgentRole, string> = {
  planner:  '#60a5fa',
  builder:  '#a78bfa',
  reviewer: '#a50e1c',
  tester:   '#34d399',
  ui_agent: '#fbbf24',
};

export const SessionSetup: React.FC = () => {
  const { defaultRoleModels } = useSettingsStore();
  const { createSession } = useSessionStore();
  const { setActivePage } = useUIStore();
  const { openDirectoryDialog } = useTauri();

  const [projectPath, setProjectPath] = useState('');
  const [task, setTask] = useState('');
  const [enabledRoles, setEnabledRoles] = useState<Record<AgentRole, boolean>>({
    planner:  true,
    builder:  true,
    reviewer: true,
    tester:   true,
    ui_agent: true,
  });

  const handleSelectFolder = async () => {
    try {
      const path = await openDirectoryDialog();
      if (path) setProjectPath(path);
    } catch (e) {
      console.error(e);
    }
  };

  const handleStart = () => {
    if (!projectPath || !task) return;
    const roleConfigs = Object.entries(enabledRoles).map(([r, enabled]) => {
      const role = r as AgentRole;
      const def = defaultRoleModels[role] || { providerId: 'default', modelId: 'gpt-4o-mini', displayName: 'Default Model' };
      return { role, enabled, provider_id: def.providerId, model_id: def.modelId, modelRef: def };
    });
    createSession({ projectPath, task, roleConfigs });
    setActivePage('session');
  };

  const isReady = projectPath && task && Object.values(enabledRoles).some(v => v);

  return (
    <div className="session-setup">
      <div className="setup-inner">

        {/* ── Header ──────────────────────────────────────── */}
        <div className="setup-header">
          <button className="setup-back-btn" onClick={() => setActivePage('dashboard')} title="Back">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="19" y1="12" x2="5" y2="12" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
          </button>
          <div>
            <h1 className="setup-title">New Session</h1>
            <p className="setup-subtitle">Configure your orchestration session</p>
          </div>
        </div>

        {/* ── Two column layout ───────────────────────────── */}
        <div className="setup-grid">

          {/* ── Left: Project config ──────────────────────── */}
          <div className="setup-col">

            {/* Project Workspace card */}
            <div className="setup-card">
              <div className="setup-card-label">1 — PROJECT WORKSPACE</div>

              <div className="setup-field">
                <label className="setup-label">Project Path</label>
                <div className="setup-path-row">
                  <input
                    className="argus-input"
                    value={projectPath}
                    readOnly
                    placeholder="Select a directory…"
                  />
                  <button className="setup-browse-btn" onClick={handleSelectFolder}>
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                    </svg>
                    Browse
                  </button>
                </div>
              </div>

              <div className="setup-field">
                <label className="setup-label">Task Description</label>
                <textarea
                  className="setup-textarea"
                  placeholder="What should the agents build or fix? Be specific and detailed."
                  value={task}
                  onChange={(e) => setTask(e.target.value)}
                />
              </div>
            </div>

            {/* Initialize button */}
            <button
              className="setup-init-btn"
              onClick={handleStart}
              disabled={!isReady}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
              Initialize Agents
            </button>
          </div>

          {/* ── Right: Agent roster ───────────────────────── */}
          <div className="setup-col">
            <div className="setup-card">
              <div className="setup-card-label">2 — AGENT ROSTER</div>

              <div className="setup-agents-list">
                {(Object.keys(AGENT_ROLE_META) as AgentRole[]).map(role => {
                  const meta = AGENT_ROLE_META[role];
                  const isEnabled = enabledRoles[role];
                  const color = roleIconColors[role];

                  return (
                    <div key={role} className={`setup-agent-row ${isEnabled ? 'setup-agent-row--enabled' : 'setup-agent-row--disabled'}`}>
                      <div className="setup-agent-left">
                        <span className="setup-agent-dot" style={{ backgroundColor: color, boxShadow: `0 0 6px ${color}55` }} />
                        <div className="setup-agent-info">
                          <span className="setup-agent-name">{meta.label}</span>
                          <span className="setup-agent-model">
                            {defaultRoleModels[role] ? 'Model configured' : 'Default model'}
                          </span>
                        </div>
                      </div>

                      {/* Toggle switch */}
                      <label className="setup-toggle" title={isEnabled ? 'Disable' : 'Enable'}>
                        <input
                          type="checkbox"
                          checked={isEnabled}
                          onChange={(e) => setEnabledRoles({ ...enabledRoles, [role]: e.target.checked })}
                        />
                        <span className="setup-toggle-track">
                          <span className="setup-toggle-thumb" />
                        </span>
                      </label>
                    </div>
                  );
                })}
              </div>

              <p className="setup-agents-hint">Configure models per agent in Settings.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
