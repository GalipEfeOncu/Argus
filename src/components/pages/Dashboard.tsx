import React from 'react';
import { useSessionStore } from '@/stores/sessionStore';
import { useUIStore } from '@/stores/uiStore';
import { useWorkspaceStore } from '@/stores/workspaceStore';
import { useWorkspaceCatalog } from '@/hooks/useWorkspaceCatalog';
import { formatRelativeTime } from '@/utils/formatters';
import './Dashboard.css';

export const Dashboard: React.FC = () => {
  const { setActiveSession } = useSessionStore();
  const { setActivePage } = useUIStore();
  const { refresh } = useWorkspaceCatalog();
  const sessions = useWorkspaceStore((state) => state.sessions);
  const projects = useWorkspaceStore((state) => state.projects);
  const selectedProjectId = useWorkspaceStore((state) => state.selectedProjectId);
  const selectProject = useWorkspaceStore((state) => state.selectProject);
  const loading = useWorkspaceStore((state) => state.loading);
  const error = useWorkspaceStore((state) => state.error);
  const visibleSessions = selectedProjectId === null ? sessions : sessions.filter((session) => session.projectId === selectedProjectId);
  const selectedProject = projects.find((project) => project.id === selectedProjectId);

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
            <h1 className="dashboard-title">{selectedProject?.displayName ?? 'Local workspace'}</h1>
            <p className="dashboard-subtitle">{selectedProject?.canonicalPath ?? 'Durable projects and Coordinator sessions on this device'}</p>
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
        <div className="dashboard-section-heading">
          <div className="dashboard-section-label">RECENT SESSIONS</div>
          {selectedProjectId !== null && <button type="button" className="dashboard-clear-filter" onClick={() => selectProject(null)}>Show all projects</button>}
        </div>

        {loading && sessions.length === 0 ? (
          <div className="dashboard-empty" role="status"><p className="dashboard-empty-title">Loading local sessions…</p></div>
        ) : <>
          {error !== null && <div className="dashboard-catalog-alert" role="alert"><span>{error}</span><button type="button" onClick={() => void refresh()}>Retry</button></div>}
          {visibleSessions.length === 0 ? (
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
            {visibleSessions.map((session) => (
              <article
                key={session.id}
                className="session-card"
              >
                {/* Status indicator row */}
                <div className="session-card-top">
                  <span className={`session-status-dot ${
                    ['completed', 'completed_partial', 'cancelled'].includes(session.status) ? 'session-status-dot--idle' :
                    ['error', 'failed'].includes(session.status) ? 'session-status-dot--error' :
                    'session-status-dot--active'
                  }`} />
                  <span className="session-status-label">
                    {session.status.replaceAll('_', ' ')}
                  </span>
                </div>

                <button type="button" className="session-open-button" onClick={() => handleOpenSession(session.id)}>
                  <span className="session-name">{session.name}</span>
                  <span className="session-goal">{session.goal}</span>
                  <span className="session-project">{session.projectDisplayName}</span>
                </button>

                <div className="session-meta">
                  <span>{formatRelativeTime(session.startedAtMs)}</span>
                </div>
              </article>
            ))}
          </div>
          )}
        </>}
      </div>
    </div>
  );
};
