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
  const enabledRoles: AgentRole[] = session.roleConfigs
    .filter(rc => rc.enabled)
    .map(rc => rc.role as AgentRole)
    .sort((a, b) => {
      const order: Record<AgentRole, number> = { coordinator: 1, planner: 2, ui_agent: 3, builder: 4, reviewer: 5, tester: 6 };
      return (order[a] || 99) - (order[b] || 99);
    });

  // Determine active node
  const activeRole = Object.keys(agents).find(
    role => agents[role as AgentRole]?.status !== 'idle' && agents[role as AgentRole]?.status !== 'done'
  ) as AgentRole | undefined;

  const activeIndex = activeRole ? enabledRoles.indexOf(activeRole) : -1;

  return (
    <div className="workflow-mini flex flex-col items-center justify-center p-6 w-full h-full glass">
      <h3 className="text-sm font-semibold text-secondary mb-8 uppercase tracking-widest">Workflow Execution Map</h3>
      
      <div className="flex items-center justify-center relative">
        {/* Connecting Line */}
        <div className="absolute top-1/2 left-0 right-0 h-[2px] bg-border-medium -translate-y-1/2 z-0">
          {activeIndex >= 0 && (
            <div 
              className="h-full bg-accent-cyan transition-all duration-700 ease-in-out shadow-[0_0_8px_var(--accent-cyan)]"
              style={{ width: `${(activeIndex / Math.max(1, enabledRoles.length - 1)) * 100}%` }}
            />
          )}
        </div>

        {enabledRoles.map((role, idx) => {
          const isDone = agents[role]?.status === 'done' || (activeIndex > idx && activeIndex !== -1);
          const isActive = role === activeRole;
          const isNext = activeIndex === -1 ? idx === 0 : idx === activeIndex + 1;

          return (
            <div key={role} className="flex items-center">
              <WorkflowNode 
                role={role} 
                isActive={isActive}
                isDone={isDone}
                isNext={isNext}
              />
              {idx < enabledRoles.length - 1 && (
                <div className="w-8 md:w-16 h-0"></div> // Spacer for the line
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
