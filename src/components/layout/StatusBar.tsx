import React from 'react';
import { useAgentStore } from '@/stores/agentStore';
import { formatTokens } from '@/utils/formatters';
import type { BackendStatus } from '@/hooks/useTauri';

interface StatusBarProps {
  backendStatus: BackendStatus;
}

const statusConfig: Record<BackendStatus, { label: string; color: string; pulse: boolean }> = {
  starting: { label: 'Starting…',  color: 'bg-accent-yellow', pulse: true  },
  running:  { label: 'Connected',  color: 'bg-accent-cyan',   pulse: false },
  stopped:  { label: 'Offline',    color: 'bg-gray-500',      pulse: false },
  error:    { label: 'Error',      color: 'bg-red-500',       pulse: true  },
};

export const StatusBar: React.FC<StatusBarProps> = ({ backendStatus }) => {
  const { agents } = useAgentStore();
  const totalTokens = Object.values(agents).reduce(
    (acc, agent) => acc + (agent.tokenCount || 0),
    0
  );

  const { label, color, pulse } = statusConfig[backendStatus];

  return (
    <footer className="h-8 glass-heavy border-t border-border-strong flex items-center justify-between px-4 text-xs text-muted relative z-40">
      <div className="flex items-center gap-4">
        <span>Argus Engine</span>
        {totalTokens > 0 && (
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-accent-cyan animate-pulse" />
            {formatTokens(totalTokens)} tokens this session
          </span>
        )}
      </div>

      <div className="flex items-center gap-4">
        {/* Backend connection indicator */}
        <span className="flex items-center gap-1.5">
          <span
            className={`w-2 h-2 rounded-full ${color} ${pulse ? 'animate-pulse' : ''}`}
          />
          Backend: {label}
        </span>
        <span>ws://127.0.0.1:8000</span>
      </div>
    </footer>
  );
};
