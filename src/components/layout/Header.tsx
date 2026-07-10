import React from 'react';
import { useSessionStore } from '@/stores/sessionStore';
import { useUIStore } from '@/stores/uiStore';
import './Header.css';

export const Header: React.FC = () => {
  const { getActiveSession } = useSessionStore();
  const { toggleAgentPanel, toggleWorkflow } = useUIStore();
  const session = getActiveSession();

  return (
    <header className="app-header h-14 flex items-center justify-between px-4 glass border-b border-border-medium relative z-30">
      <div className="flex items-center gap-4">
        {session ? (
          <>
            <h2 className="font-semibold text-primary">{session.name}</h2>
            <div className={`text-xs px-2 py-0.5 rounded border 
              ${session.status === 'completed' ? 'border-accent-green text-accent-green' : 
                session.status === 'error' ? 'border-accent-red text-accent-red' : 
                'border-accent-cyan text-accent-cyan'}`}
            >
              {session.status.toUpperCase()}
            </div>
          </>
        ) : (
          <h2 className="font-semibold text-secondary">No Active Session</h2>
        )}
      </div>

      <div className="flex items-center gap-3">
        <button 
          className="header-btn text-sm text-secondary hover:text-primary px-3 py-1.5 rounded bg-white/5 border border-white/10 hover:bg-white/10 transition-colors"
          onClick={toggleWorkflow}
        >
          Workflow Map
        </button>
        <button 
          className="header-btn text-sm text-secondary hover:text-primary px-3 py-1.5 rounded bg-white/5 border border-white/10 hover:bg-white/10 transition-colors"
          onClick={toggleAgentPanel}
        >
          Agents Panel
        </button>
      </div>
    </header>
  );
};
