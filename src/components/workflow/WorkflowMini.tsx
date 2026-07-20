import React from 'react';
import { useSessionStore } from '@/stores/sessionStore';
import { useAgentStore } from '@/stores/agentStore';
import { WorkflowNode } from './WorkflowNode';
import type { AgentRole } from '@/types/agent';
import './WorkflowMini.css';

export const WorkflowMini: React.FC = () => {
  const { getActiveSession } = useSessionStore();
  const { agents } = useAgentStore();
  const session = getActiveSession();

  if (!session) return null;

  // The order is roughly Planner -> Builder <-> Reviewer -> Tester (UI agent may parallel Builder)
  const enabledAgents = session.roleConfigs
    .filter(rc => rc.enabled)
    .map((rc) => ({ id: rc.instanceId ?? rc.role, role: rc.role as AgentRole }))
    .sort((a, b) => {
      const order: Record<AgentRole, number> = { coordinator: 1, planner: 2, ui_agent: 3, builder: 4, reviewer: 5, tester: 6 };
      return (order[a.role] || 99) - (order[b.role] || 99);
    });

  // Determine active node
  const activeAgentId = Object.keys(agents).find(
    (id) => agents[id]?.status !== 'idle' && agents[id]?.status !== 'done'
  );

  const activeIndex = activeAgentId ? enabledAgents.findIndex((agent) => agent.id === activeAgentId) : -1;

  return (
    <div className="workflow-mini flex flex-col items-center justify-center p-6 w-full h-full glass">
      <h3 className="text-sm font-semibold text-secondary mb-8 uppercase tracking-widest">Workflow Execution Map</h3>
      
      <div className="flex items-center justify-center relative">
        {/* Connecting Line */}
        <div className="absolute top-1/2 left-0 right-0 h-[2px] bg-border-medium -translate-y-1/2 z-0">
          {activeIndex >= 0 && (
            <div 
              className="h-full bg-accent-cyan transition-all duration-700 ease-in-out shadow-[0_0_8px_var(--accent-cyan)]"
              style={{ width: `${(activeIndex / Math.max(1, enabledAgents.length - 1)) * 100}%` }}
            />
          )}
        </div>

        {enabledAgents.map((agent, idx) => {
          const isDone = agents[agent.id]?.status === 'done' || (activeIndex > idx && activeIndex !== -1);
          const isActive = agent.id === activeAgentId;
          const isNext = activeIndex === -1 ? idx === 0 : idx === activeIndex + 1;

          return (
            <div key={agent.id} className="flex items-center">
              <WorkflowNode 
                role={agent.role}
                isActive={isActive}
                isDone={isDone}
                isNext={isNext}
              />
              {idx < enabledAgents.length - 1 && (
                <div className="w-8 md:w-16 h-0"></div> // Spacer for the line
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
