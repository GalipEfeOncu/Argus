import React from 'react';
import { useAgentStore } from '@/stores/agentStore';
import { formatTokens } from '@/utils/formatters';
import type { BackendStatus } from '@/hooks/useTauri';
import './StatusBar.css';

interface StatusBarProps {
  backendStatus: BackendStatus;
}

const statusConfig: Record<BackendStatus, { label: string; dotClass: string; pulse: boolean }> = {
  starting: { label: 'Starting local runtime…', dotClass: 'statusbar-dot--warning', pulse: true },
  running:  { label: 'Local runtime running', dotClass: 'statusbar-dot--active', pulse: false },
  stopped:  { label: 'Local runtime stopped', dotClass: 'statusbar-dot--idle', pulse: false },
  error:    { label: 'Local runtime error', dotClass: 'statusbar-dot--error', pulse: true },
};

export const StatusBar: React.FC<StatusBarProps> = ({ backendStatus }) => {
  const { agents } = useAgentStore();
  const totalTokens = Object.values(agents).reduce(
    (acc, agent) => acc + (agent.tokenCount || 0),
    0
  );

  const { label, dotClass, pulse } = statusConfig[backendStatus];

  return (
    <footer className="statusbar">
      {/* Left: backend status */}
      <div className="statusbar-section statusbar-section--left">
        <span className={`statusbar-dot ${dotClass} ${pulse ? 'statusbar-dot--pulse' : ''}`} />
        <span>{label}</span>
      </div>

      {/* Center: token count */}
      <div className="statusbar-section statusbar-section--center">
        {totalTokens > 0 && (
          <span>Session tokens: {formatTokens(totalTokens)}</span>
        )}
      </div>

      <div className="statusbar-section statusbar-section--right" aria-hidden="true" />
    </footer>
  );
};
