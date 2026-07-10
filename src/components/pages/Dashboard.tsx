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
    <div className="dashboard p-8 w-full max-w-5xl mx-auto animation-fade-in">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-primary mb-2" style={{ textShadow: '0 0 20px rgba(0, 229, 255, 0.4)' }}>
            Welcome to Argus
          </h1>
          <p className="text-secondary">Transparent multi-agent orchestration platform.</p>
        </div>
        <button 
          className="btn btn-primary bg-accent-cyan/20 text-accent-cyan border border-accent-cyan/50 hover:bg-accent-cyan/30 px-4 py-2 rounded shadow-[0_0_15px_rgba(0,229,255,0.3)] transition-all"
          onClick={() => setActivePage('session-setup')}
        >
          + New Session
        </button>
      </div>

      <div className="recent-sessions">
        <h2 className="text-xl font-semibold text-primary mb-4 border-b border-border-medium pb-2">Recent Sessions</h2>
        
        {sessions.length === 0 ? (
          <div className="glass-surface rounded-lg p-12 text-center text-muted border border-border-subtle">
            <div className="text-4xl mb-4 opacity-50">📂</div>
            <p className="mb-4">No recent sessions found.</p>
            <button 
              className="text-accent-cyan hover:underline"
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
                className="session-card glass-card p-4 hover:border-accent-cyan/50 transition-colors cursor-pointer group"
                onClick={() => handleOpenSession(session.id)}
              >
                <div className="flex justify-between items-start mb-2">
                  <h3 className="font-semibold text-primary truncate pr-2">{session.name}</h3>
                  <button 
                    className="opacity-0 group-hover:opacity-100 text-muted hover:text-red-400 transition-opacity"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteSession(session.id);
                    }}
                  >
                    ✕
                  </button>
                </div>
                <div className="text-xs text-muted mb-3 line-clamp-2" title={session.task}>
                  {session.task}
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className={`px-2 py-0.5 rounded-full border ${
                    session.status === 'completed' ? 'border-accent-green text-accent-green' : 
                    session.status === 'error' ? 'border-accent-red text-accent-red' : 
                    'border-accent-cyan text-accent-cyan'
                  }`}>
                    {session.status}
                  </span>
                  <span className="text-muted">{formatRelativeTime(session.startedAt)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
