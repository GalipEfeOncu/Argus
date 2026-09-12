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
            <p className="dashboard-eyebrow">ARGUS / LOCAL-FIRST</p>
            <h1 className="dashboard-title">{selectedProject?.displayName ?? 'Local workspace'}</h1>
            <p className="dashboard-subtitle">{selectedProject?.canonicalPath ?? 'Durable projects and Coordinator sessions on this device'}</p>
          </div>
        </div>

        {/* ── Sessions ─────────────────────────────────────── */}
        <div className="dashboard-section-heading">
          <h2 className="dashboard-section-label">RECENT SESSIONS</h2>
          {selectedProjectId !== null && <button type="button" className="dashboard-clear-filter" onClick={() => selectProject(null)}>Show all projects</button>}
        </div>

        {loading && sessions.length === 0 ? (
          <div className="dashboard-empty" role="status"><p className="dashboard-empty-title">Loading local sessions…</p></div>
        ) : <>
          {error !== null && <div className="dashboard-catalog-alert" role="alert"><div><strong>Local catalogue unavailable</strong><span>{error}</span></div><button type="button" aria-label="Retry loading local projects and sessions" onClick={() => void refresh()}>Retry</button></div>}
          {visibleSessions.length === 0 ? (
          /* ── Empty State ─────────────────────────────────── */
          <div className="dashboard-empty">
            <p className="dashboard-empty-title">No sessions yet</p>
            <p className="dashboard-empty-sub">Start a read-only session with Coordinator and one specialist at a time.</p>
            <button
              className="dashboard-empty-cta"
              onClick={() => setActivePage('new-chat')}
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
