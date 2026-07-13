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
    <div className="dashboard">
      <div className="dashboard-inner">

        {/* ── Header ──────────────────────────────────────── */}
        <div className="dashboard-header">
          <div>
            <h1 className="dashboard-title">Dashboard</h1>
            <p className="dashboard-subtitle">Multi-agent orchestration</p>
          </div>
          <button
            className="dashboard-new-btn"
            onClick={() => setActivePage('session-setup')}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            New Session
          </button>
        </div>

        {/* ── Sessions ─────────────────────────────────────── */}
        <div className="dashboard-section-label">RECENT SESSIONS</div>

        {sessions.length === 0 ? (
          /* ── Empty State ─────────────────────────────────── */
          <div className="dashboard-empty">
            <div className="dashboard-empty-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <p className="dashboard-empty-title">No sessions yet</p>
            <p className="dashboard-empty-sub">Start a new orchestration to put your agents to work.</p>
            <button
              className="dashboard-empty-cta"
              onClick={() => setActivePage('session-setup')}
            >
              Start your first session
            </button>
          </div>
        ) : (
          /* ── Session Grid ─────────────────────────────────── */
          <div className="dashboard-grid">
            {sessions.map((session) => (
              <div
                key={session.id}
                className="session-card group"
                onClick={() => handleOpenSession(session.id)}
              >
                {/* Status indicator row */}
                <div className="session-card-top">
                  <span className={`session-status-dot ${
                    session.status === 'completed' ? 'session-status-dot--idle' :
                    session.status === 'error'     ? 'session-status-dot--error' :
                    'session-status-dot--active'
                  }`} />
                  <span className="session-status-label">
                    {session.status === 'completed' ? 'Ended' : session.status === 'error' ? 'Error' : 'Active'}
                  </span>
                  <button
                    className="session-delete-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteSession(session.id);
                    }}
                    title="Delete session"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
                    </svg>
                  </button>
                </div>

                <h3 className="session-name">{session.name}</h3>

                <div className="session-meta">
                  <span>{formatRelativeTime(session.startedAt)}</span>
                </div>

                <div className="session-open-hint">
                  Open session →
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
