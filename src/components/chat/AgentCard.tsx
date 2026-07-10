import React from 'react';
import type { AgentInfo } from '@/types/agent';
import { AGENT_ROLE_META } from '@/types/agent';
import { AgentAvatar } from './AgentAvatar';
import './AgentCard.css';

interface AgentCardProps {
  agent: AgentInfo;
  onClick?: () => void;
}

export const AgentCard: React.FC<AgentCardProps> = ({ agent, onClick }) => {
  const meta = AGENT_ROLE_META[agent.role];
  const isActive = agent.status !== 'idle' && agent.status !== 'done';

  return (
    <div 
      className={`agent-card glass-card flex flex-col p-3 ${isActive ? 'agent-card-active' : ''}`}
      onClick={onClick}
      style={{
        '--agent-color': `var(${meta.colorVar})`,
        '--agent-glow': `var(${meta.colorVar}-glow)`,
      } as React.CSSProperties}
    >
      <div className="flex items-center gap-3 mb-2">
        <AgentAvatar role={agent.role} size="md" isPulsing={isActive} />
        <div className="flex-1 min-w-0">
          <div className="agent-role-name font-semibold truncate text-primary">{meta.label}</div>
          <div className="agent-status-text text-xs text-muted truncate">
            {agent.status === 'idle' ? 'Ready' : 
             agent.status === 'done' ? 'Completed' : 
             agent.currentAction || agent.status}
          </div>
        </div>
      </div>
      
      <div className="agent-stats flex justify-between mt-2 pt-2 border-t border-white/5">
        <div className="stat text-xs">
          <span className="text-muted">Tokens: </span>
          <span className="text-secondary font-mono">{agent.tokenCount}</span>
        </div>
        <div className="stat text-xs">
          <span className="text-muted">Status: </span>
          <span className={`status-dot ${agent.status}`} />
        </div>
      </div>
    </div>
  );
};
