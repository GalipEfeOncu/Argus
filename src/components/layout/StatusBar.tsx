import React from 'react';
import { useAgentStore } from '@/stores/agentStore';
import { formatTokens } from '@/utils/formatters';
import type { BackendStatus } from '@/hooks/useTauri';
import './StatusBar.css';

interface StatusBarProps {
  backendStatus: BackendStatus;
}

const statusConfig: Record<BackendStatus, { label: string; dotClass: string; pulse: boolean }> = {
  starting: { label: 'Starting…',  dotClass: 'statusbar-dot--warning', pulse: true  },
  running:  { label: 'Connected',  dotClass: 'statusbar-dot--active',  pulse: false },
  stopped:  { label: 'Offline',    dotClass: 'statusbar-dot--idle',    pulse: false },
  error:    { label: 'Error',      dotClass: 'statusbar-dot--error',   pulse: true  },
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
        <span>Backend: {label}</span>
      </div>

      {/* Center: token count */}
      <div className="statusbar-section statusbar-section--center">
        {totalTokens > 0 && (
          <span>Session tokens: {formatTokens(totalTokens)}</span>
        )}
      </div>

      {/* Right: WS endpoint */}
      <div className="statusbar-section statusbar-section--right">
        <span className="statusbar-ws">ws://127.0.0.1:8000</span>
      </div>
    </footer>
  );
};
