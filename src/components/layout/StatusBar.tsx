import React from 'react';
import { useAgentStore } from '@/stores/agentStore';
import { formatTokens } from '@/utils/formatters';

export const StatusBar: React.FC = () => {
  const { agents } = useAgentStore();
  
  const totalTokens = Object.values(agents).reduce((acc, agent) => acc + (agent.tokenCount || 0), 0);

  return (
    <footer className="h-8 glass-heavy border-t border-border-strong flex items-center justify-between px-4 text-xs text-muted relative z-40">
      <div className="flex items-center gap-4">
        <span>Argus Engine Active</span>
        {totalTokens > 0 && (
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-accent-cyan animate-pulse"></span>
            {formatTokens(totalTokens)} Tokens Session Total
          </span>
        )}
      </div>
      <div className="flex items-center gap-4">
        <span>Backend: ws://127.0.0.1:8000</span>
        <span>Memory: ~</span>
      </div>
    </footer>
  );
};
