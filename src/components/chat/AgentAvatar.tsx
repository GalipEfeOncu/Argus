import React from 'react';
import type { AgentRole } from '@/types/agent';
import { AGENT_ROLE_META } from '@/types/agent';
import './AgentAvatar.css';

interface AgentAvatarProps {
  role: AgentRole;
  size?: 'sm' | 'md' | 'lg';
  isPulsing?: boolean;
}

export const AgentAvatar: React.FC<AgentAvatarProps> = ({ role, size = 'md', isPulsing = false }) => {
  const meta = AGENT_ROLE_META[role];

  return (
    <div
      className={`agent-avatar agent-avatar-${size} ${isPulsing ? 'agent-avatar-pulsing' : ''}`}
      style={{
        '--avatar-color': `var(${meta.colorVar})`,
        '--avatar-glow': `var(${meta.colorVar}-glow)`,
      } as React.CSSProperties}
      title={meta.label}
    >
      <span className="agent-avatar-emoji">{meta.emoji}</span>
    </div>
  );
};
