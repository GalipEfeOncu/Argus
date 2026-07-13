import React from 'react';
import { useSessionStore } from '@/stores/sessionStore';
import { useUIStore } from '@/stores/uiStore';
import { formatRelativeTime } from '@/utils/formatters';
import './Dashboard.css';

export const Dashboard: React.FC = () => {
  const { sessions, setActiveSession, deleteSession } = useSessionStore();
  const { setActivePage } = useUIStore();

  const handleOpenSession = (id: string) => {
    setActiveSession(id);
    setActivePage('session');
  };

  return (
    <div className="dashboard h-full w-full bg-[var(--bg-main)] p-8 overflow-y-auto">
      <div className="max-w-5xl mx-auto">
        <div className="flex justify-between items-start mb-8">
          <div>
            <h1 className="text-2xl font-bold text-primary mb-1">
              Dashboard
            </h1>
            <p className="text-secondary text-sm">Multi-agent orchestration</p>
          </div>
          <button 
            className="bg-accent-primary hover:bg-accent-hover text-primary px-4 py-2 rounded-md font-medium transition-colors text-sm"
            onClick={() => setActivePage('session-setup')}
          >
            New Session
          </button>
        </div>

        <div className="recent-sessions">
          {sessions.length === 0 ? (
            <div className="rounded-md p-12 text-center text-muted border border-border-subtle bg-[var(--bg-card)]">
              <p className="mb-4">No recent sessions found.</p>
              <button 
                className="text-primary underline hover:text-secondary text-sm"
                onClick={() => setActivePage('session-setup')}
              >
                Start a new orchestration session
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {sessions.map((session) => (
                <div 
                  key={session.id} 
                  className="session-card bg-[var(--bg-card)] border border-border-subtle p-5 rounded-md hover:border-border-focus hover:bg-[var(--bg-card-hover)] transition-all cursor-pointer group flex flex-col"
                  onClick={() => handleOpenSession(session.id)}
                >
                  <div className="flex justify-between items-start mb-4">
                    <h3 className="font-medium text-primary truncate pr-2 text-base">{session.name}</h3>
                    <div className="flex items-center gap-2">
                      <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-sm bg-[#111111] border border-border-subtle text-xs text-secondary">
                        <span className={`w-1.5 h-1.5 rounded-full ${
                          session.status === 'completed' ? 'bg-[var(--status-idle)]' : 
                          session.status === 'error' ? 'bg-[var(--status-error)]' : 
                          'bg-[var(--status-active)]'
                        }`} />
                        {session.status === 'completed' ? 'ended' : 'active'}
                      </span>
                    </div>
                  </div>
                  
                  <div className="text-xs text-secondary mb-4 flex-1">
                    <div className="mb-1">{formatRelativeTime(session.startedAt)}</div>
                    <div>Model</div>
                    <div className="text-muted truncate">Models 3, Claude 3.5 Sonnet</div>
                  </div>
                  
                  <div className="flex justify-between items-center mt-auto">
                     <button 
                      className="opacity-0 group-hover:opacity-100 text-muted hover:text-[var(--status-error)] transition-opacity text-xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        deleteSession(session.id);
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
