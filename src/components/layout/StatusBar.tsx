import React from 'react';
import { useAgentStore } from '@/stores/agentStore';
import { formatTokens } from '@/utils/formatters';
import type { BackendStatus } from '@/hooks/useTauri';

interface StatusBarProps {
  backendStatus: BackendStatus;
}

const statusConfig: Record<BackendStatus, { label: string; color: string; pulse: boolean }> = {
  starting: { label: 'Starting…',  color: 'bg-[var(--status-warning)]', pulse: true  },
  running:  { label: 'Connected',  color: 'bg-[var(--status-active)]',  pulse: false },
  stopped:  { label: 'Offline',    color: 'bg-[var(--status-idle)]',    pulse: false },
  error:    { label: 'Error',      color: 'bg-[var(--status-error)]',   pulse: true  },
};

export const StatusBar: React.FC<StatusBarProps> = ({ backendStatus }) => {
  const { agents } = useAgentStore();
  const totalTokens = Object.values(agents).reduce(
    (acc, agent) => acc + (agent.tokenCount || 0),
    0
  );

  const { label, color, pulse } = statusConfig[backendStatus];

  return (
    <footer className="h-[var(--statusbar-height)] bg-[var(--bg-status)] flex items-center justify-between px-4 text-xs text-muted relative z-40">
      <div className="flex items-center gap-1.5 w-1/3">
        <span
          className={`w-1.5 h-1.5 rounded-full ${color} ${pulse ? 'animate-pulse' : ''}`}
        />
        Backend: {label}
      </div>

      <div className="flex items-center justify-center w-1/3">
        {totalTokens > 0 && (
          <span>Session token count: {formatTokens(totalTokens)}</span>
        )}
      </div>

      <div className="flex items-center justify-end w-1/3">
        <span>ws://127.0.0.1:8000</span>
      </div>
    </footer>
  );
};
