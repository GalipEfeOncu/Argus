import React, { useState } from 'react';
import { useSettingsStore } from '@/stores/settingsStore';
import { useSessionStore } from '@/stores/sessionStore';
import { useUIStore } from '@/stores/uiStore';
import { useTauri } from '@/hooks/useTauri';
import { AGENT_ROLE_META } from '@/types/agent';
import type { AgentRole } from '@/types/agent';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { Card } from '../ui/Card';
import './SessionSetup.css';

export const SessionSetup: React.FC = () => {
  const { defaultRoleModels } = useSettingsStore();
  const { createSession } = useSessionStore();
  const { setActivePage } = useUIStore();
  const { openDirectoryDialog } = useTauri();

  const [projectPath, setProjectPath] = useState('');
  const [task, setTask] = useState('');
  
  // State for enabled roles
  const [enabledRoles, setEnabledRoles] = useState<Record<AgentRole, boolean>>({
    planner: true,
    builder: true,
    reviewer: true,
    tester: true,
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

    // Create session payload
    const roleConfigs = Object.entries(enabledRoles).map(([r, enabled]) => {
      const role = r as AgentRole;
      const def = defaultRoleModels[role] || { providerId: 'default', modelId: 'gpt-4o-mini', displayName: 'Default Model' };
      return {
        role,
        enabled,
        provider_id: def.providerId,
        model_id: def.modelId,
        modelRef: def, // Satisfy RoleConfig type
      };
    });

    createSession({
      projectPath,
      task,
      roleConfigs,
    });
    
    // Switch to session view
    setActivePage('session');
  };

  const isReady = projectPath && task && Object.values(enabledRoles).some(v => v);

  return (
    <div className="session-setup p-8 max-w-4xl mx-auto w-full animation-fade-in">
      <h1 className="text-2xl font-bold text-primary mb-6 flex items-center gap-3">
        <span className="text-3xl">✨</span> New Orchestration Session
      </h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div className="space-y-6">
          <Card className="p-6">
            <h2 className="text-lg font-semibold text-primary mb-4 border-b border-border-subtle pb-2">1. Project Workspace</h2>
            
            <div className="mb-4">
              <label className="block text-sm text-secondary mb-2">Project Path</label>
              <div className="flex gap-2">
                <Input 
                  value={projectPath} 
                  readOnly 
                  placeholder="Select a directory..." 
                  className="flex-1"
                />
                <Button variant="secondary" onClick={handleSelectFolder}>Browse</Button>
              </div>
            </div>
            
            <div>
              <label className="block text-sm text-secondary mb-2">Task Description</label>
              <textarea 
                className="w-full glass-surface border border-border-strong rounded-lg p-3 text-primary focus:border-accent-cyan resize-none min-h-[120px]"
                placeholder="What should the agents build or fix? Be specific."
                value={task}
                onChange={(e) => setTask(e.target.value)}
              />
            </div>
          </Card>

          <Button 
            variant="neon" 
            size="lg" 
            className="w-full h-14 text-lg mt-4 shadow-[0_0_20px_rgba(0,229,255,0.4)]"
            onClick={handleStart}
            disabled={!isReady}
          >
            INITIALIZE AGENTS
          </Button>
        </div>

        <div className="space-y-6">
          <Card className="p-6">
            <h2 className="text-lg font-semibold text-primary mb-4 border-b border-border-subtle pb-2">2. Agent Roster</h2>
            
            <div className="space-y-3">
              {(Object.keys(AGENT_ROLE_META) as AgentRole[]).map(role => {
                const meta = AGENT_ROLE_META[role];
                const isEnabled = enabledRoles[role];
                
                return (
                  <div 
                    key={role} 
                    className={`flex items-center justify-between p-3 rounded-lg border transition-all ${
                      isEnabled ? 'border-border-strong bg-white/5' : 'border-border-subtle opacity-50'
                    }`}
                    style={{ '--agent-color': `var(${meta.colorVar})` } as React.CSSProperties}
                  >
                    <div className="flex items-center gap-3">
                      <div className="text-2xl">{meta.emoji}</div>
                      <div>
                        <div className="font-semibold" style={{ color: isEnabled ? 'var(--agent-color)' : 'var(--text-muted)' }}>
                          {meta.label}
                        </div>
                        <div className="text-xs text-muted">
                          {defaultRoleModels[role] 
                            ? 'Model Selected' 
                            : 'Using Default Model'}
                        </div>
                      </div>
                    </div>
                    
                    <div className="toggle-wrapper">
                      <input 
                        type="checkbox" 
                        id={`toggle-${role}`} 
                        className="peer sr-only"
                        checked={isEnabled}
                        onChange={(e) => setEnabledRoles({...enabledRoles, [role]: e.target.checked})}
                      />
                      <label 
                        htmlFor={`toggle-${role}`}
                        className="toggle-label block w-10 h-6 bg-bg-surface rounded-full border border-border-strong cursor-pointer relative transition-colors peer-checked:border-[var(--agent-color)] peer-checked:shadow-[0_0_10px_var(--agent-color)]"
                      >
                        <span className={`toggle-dot absolute top-[2px] left-[2px] w-4 h-4 bg-muted rounded-full transition-all peer-checked:translate-x-4 ${isEnabled ? 'bg-[var(--agent-color)]' : ''}`}></span>
                      </label>
                    </div>
                  </div>
                );
              })}
            </div>
            
            <p className="text-xs text-muted mt-4 text-center">
              Configure specific models per agent in Settings.
            </p>
          </Card>
        </div>
      </div>
    </div>
  );
};
