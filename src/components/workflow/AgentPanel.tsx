import React from 'react';
import { useAgentStore } from '@/stores/agentStore';

export const AgentPanel: React.FC = () => {
  // For the mockup phase, we'll hardcode some agent states if the store is empty
  // In Phase 1.2/1.3 this will be driven by the actual agentStore.
  const { agents } = useAgentStore();
  const activeAgents = Object.values(agents);

  // Mock data for the UI overhaul review
  const mockAgents = [
    { role: 'PLANNER', status: 'Complete', tokens: 23, color: 'bg-[var(--status-success)]' },
    { role: 'BUILDER', status: 'Writing code...', tokens: 1, color: 'bg-[var(--status-error)] pulse' },
    { role: 'REVIEWER', status: 'Waiting', tokens: 10, color: 'bg-[var(--status-idle)]' },
  ];

  const displayAgents = activeAgents.length > 0 ? activeAgents : mockAgents;

  return (
    <div className="w-[var(--agent-panel-width)] h-full bg-[var(--bg-sidebar)] border-l border-border-subtle flex flex-col p-5">
      <h2 className="text-primary font-medium mb-4">Active Agents</h2>
      
      <div className="flex flex-col gap-3 mb-8">
        {displayAgents.map((agent: any) => (
          <div key={agent.role} className="bg-[var(--bg-card)] border border-border-subtle rounded-md p-3">
            <div className="flex justify-between items-start mb-2">
              <span className="text-muted text-xs tracking-wider">{agent.role}</span>
              <span className="text-muted text-xs">{agent.tokens || agent.tokenCount || 0} tokens</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-primary text-sm">{agent.status || agent.state || 'Idle'}</span>
              <span className={`w-2 h-2 rounded-full ${
                agent.color || 
                (agent.state === 'running' ? 'bg-[var(--status-error)] animate-pulse' : 
                 agent.state === 'completed' ? 'bg-[var(--status-success)]' : 'bg-[var(--status-idle)]')
              }`} />
            </div>
          </div>
        ))}
      </div>

      <div className="mt-auto border-t border-border-subtle pt-6">
        <h2 className="text-primary font-medium mb-4">Workflow</h2>
        <div className="flex items-center text-sm gap-2 text-muted">
          <span>Planner</span>
          <span>→</span>
          <span className="text-[var(--status-error)]">Builder</span>
          <span>→</span>
          <span>Reviewer</span>
          <span>→</span>
          <span>Tester</span>
        </div>
      </div>
    </div>
  );
};
