import React from 'react';
import { useUIStore } from '@/stores/uiStore';
import { useWorkspaceStore } from '@/stores/workspaceStore';
import { useWorkspaceCatalog } from '@/hooks/useWorkspaceCatalog';
import './Sidebar.css';

/* ── Role-specific SVG icons for agent roles ── */
const AgusLogoIcon: React.FC = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2L2 7l10 5 10-5-10-5z" />
    <path d="M2 17l10 5 10-5" />
    <path d="M2 12l10 5 10-5" />
  </svg>
);

const ChevronLeftIcon: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="15 18 9 12 15 6" />
  </svg>
);

const ChevronRightIcon: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="9 18 15 12 9 6" />
  </svg>
);

export const Sidebar: React.FC = () => {
  const { activePage, setActivePage, sidebarCollapsed, toggleSidebar } = useUIStore();
  const { refresh } = useWorkspaceCatalog();
  const projects = useWorkspaceStore((state) => state.projects);
  const selectedProjectId = useWorkspaceStore((state) => state.selectedProjectId);
  const loading = useWorkspaceStore((state) => state.loading);
  const error = useWorkspaceStore((state) => state.error);
  const selectProject = useWorkspaceStore((state) => state.selectProject);

  const handleNewSession = () => {
    setActivePage('session-setup');
  };

  const navItems = [
    {
      id: 'settings',
      label: 'Settings',
      icon: (
        <svg className="nav-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      ),
      action: () => setActivePage('settings'),
    },
  ] as const;

  const openProject = (projectId: string) => {
    selectProject(projectId);
    setActivePage('dashboard');
  };

  return (
    <aside className={`sidebar flex flex-col transition-all duration-200 ${sidebarCollapsed ? 'sidebar-collapsed' : 'sidebar-expanded'}`}>
      
      {/* ── Logo Header ─────────────────────────────────── */}
      <div className="sidebar-header flex items-center justify-between px-3 py-3">
        {!sidebarCollapsed ? (
          <div className="flex items-center gap-2.5 select-none">
            {/* Red icon box */}
            <div className="logo-icon-box">
              <AgusLogoIcon />
            </div>
            <span className="logo-wordmark">ARGUS</span>
          </div>
        ) : (
          <div className="logo-icon-box logo-icon-box--center">
            <AgusLogoIcon />
          </div>
        )}

        <button 
          className="sidebar-toggle-btn"
          onClick={toggleSidebar}
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {sidebarCollapsed ? <ChevronRightIcon /> : <ChevronLeftIcon />}
        </button>
      </div>

      {/* ── New Session Button ───────────────────────────── */}
      <div className="px-3 pb-2">
        <button
          onClick={handleNewSession}
          className={`btn-new-session flex items-center justify-center gap-2 font-semibold text-sm transition-all w-full ${sidebarCollapsed ? 'btn-new-session--icon' : 'btn-new-session--full'}`}
          title="New Session"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          {!sidebarCollapsed && <span>New Session</span>}
        </button>
      </div>

      {/* ── Main Navigation ─────────────────────────────── */}
      <nav className="py-1 flex flex-col gap-0.5 px-2">
        {navItems.map((item) => (
          <button
            key={item.id}
            onClick={item.action}
            className={`nav-row flex items-center gap-3 px-2 py-2 rounded-md transition-colors text-sm font-medium ${
              activePage === item.id 
                ? 'nav-row--active' 
                : 'nav-row--default'
            } ${sidebarCollapsed ? 'justify-center' : 'justify-start'}`}
            title={sidebarCollapsed ? item.label : undefined}
          >
            {item.icon}
            {!sidebarCollapsed && <span>{item.label}</span>}
          </button>
        ))}
      </nav>

      {/* ── Projects Section ─────────────────────────────── */}
      <div className="flex-1 py-3 flex flex-col overflow-hidden">
        {!sidebarCollapsed ? (
          <>
            <div className="projects-header px-4 py-1.5 flex items-center justify-between">
              <span className="projects-label">PROJECTS</span>
            </div>
            <div className="flex-1 overflow-y-auto px-2 flex flex-col gap-0.5 projects-scroll" aria-live="polite">
              {loading && <p className="projects-state" role="status">Loading local projects…</p>}
              {!loading && error !== null && <div className="projects-state" role="alert"><span>{error}</span><button type="button" onClick={() => void refresh()}>Retry</button></div>}
              {!loading && error === null && projects.length === 0 && <p className="projects-state">No local projects registered.</p>}
              {!loading && error === null && projects.map((project) => (
                <button
                  key={project.id}
                  onClick={() => openProject(project.id)}
                  aria-label={project.displayName}
                  className={`project-row flex items-center px-3 py-1.5 rounded-md text-sm transition-colors text-left w-full ${
                    project.id === selectedProjectId
                      ? 'project-row--active' 
                      : 'project-row--default'
                  }`}
                >
                  <span className="project-hash">#</span>
                  <span className="truncate">{project.displayName}</span>
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="flex flex-col items-center gap-1.5 py-2 border-t border-border-subtle mt-1 px-1">
            <span className="text-muted text-[8px] font-bold tracking-wider uppercase mb-1">PRJ</span>
            {error !== null && <button type="button" className="project-avatar-pill project-avatar-pill--default" onClick={() => void refresh()} title="Retry loading local projects">!</button>}
            {error === null && projects.map((project) => (
                <button
                  key={project.id}
                  onClick={() => openProject(project.id)}
                  aria-label={project.displayName}
                className={`project-avatar-pill w-7 h-7 rounded flex items-center justify-center text-[10px] font-bold transition-colors ${
                  project.id === selectedProjectId
                    ? 'project-avatar-pill--active' 
                    : 'project-avatar-pill--default'
                }`}
                title={project.displayName}
              >
                {project.displayName.charAt(0).toUpperCase()}
              </button>
            ))}
          </div>
        )}
      </div>

    </aside>
  );
};
