import React from 'react';
import type { AgentRole } from '@/types/agent';
import { AGENT_ROLE_META } from '@/types/agent';
import './WorkflowNode.css';

interface WorkflowNodeProps {
  role: AgentRole;
  isActive: boolean;
  isDone: boolean;
  isNext: boolean;
}

export const WorkflowNode: React.FC<WorkflowNodeProps> = ({ role, isActive, isDone, isNext }) => {
  const meta = AGENT_ROLE_META[role];

  let stateClass = 'node-idle';
  if (isActive) stateClass = 'node-active';
  else if (isDone) stateClass = 'node-done';
  else if (isNext) stateClass = 'node-next';

  return (
    <div 
      className={`workflow-node ${stateClass} flex flex-col items-center justify-center p-2 rounded-lg transition-all duration-300 glass-card`}
      style={{
        '--node-color': `var(${meta.colorVar})`,
        '--node-glow': `var(${meta.colorVar}-glow)`,
      } as React.CSSProperties}
    >
      <div className="node-icon text-2xl mb-1">{meta.emoji}</div>
      <div className="node-label text-xs font-semibold text-primary">{meta.label}</div>
    </div>
  );
};
