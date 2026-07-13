import React from 'react';
import { useUIStore } from '@/stores/uiStore';
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

  const handleNewSession = () => {
    setActivePage('session-setup');
  };

  const navItems = [
    {
      id: 'search',
      label: 'Search',
      icon: (
        <svg className="nav-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
      ),
      action: () => {},
    },
    {
      id: 'history',
      label: 'History',
      icon: (
        <svg className="nav-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      ),
      action: () => setActivePage('history'),
    },
    {
      id: 'scheduled-tasks',
      label: 'Scheduled Tasks',
      icon: (
        <svg className="nav-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      ),
      action: () => {},
    },
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

  const mockProjects = [
    { id: 'argus-backend', name: 'argus-backend', active: false },
    { id: 'argus-frontend', name: 'argus-frontend', active: true },
    { id: 'cli-tool', name: 'cli-tool', active: false },
    { id: 'design-system', name: 'design-system', active: false },
  ];

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
              <div className="projects-actions">
                <button className="projects-action-btn" title="Search projects">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                </button>
                <button className="projects-action-btn" title="Filter">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
                  </svg>
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto px-2 flex flex-col gap-0.5 projects-scroll">
              {mockProjects.map((project) => (
                <button
                  key={project.id}
                  onClick={() => setActivePage('session')}
                  className={`project-row flex items-center px-3 py-1.5 rounded-md text-sm transition-colors text-left w-full ${
                    project.active 
                      ? 'project-row--active' 
                      : 'project-row--default'
                  }`}
                >
                  <span className="project-hash">#</span>
                  <span className="truncate">{project.name}</span>
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="flex flex-col items-center gap-1.5 py-2 border-t border-border-subtle mt-1 px-1">
            <span className="text-muted text-[8px] font-bold tracking-wider uppercase mb-1">PRJ</span>
            {mockProjects.map((project) => (
              <button
                key={project.id}
                onClick={() => setActivePage('session')}
                className={`project-avatar-pill w-7 h-7 rounded flex items-center justify-center text-[10px] font-bold transition-colors ${
                  project.active 
                    ? 'project-avatar-pill--active' 
                    : 'project-avatar-pill--default'
                }`}
                title={project.name}
              >
                {project.name.charAt(0).toUpperCase()}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── User Profile Footer ──────────────────────────── */}
      <div className="sidebar-footer border-t border-border-subtle p-3">
        <div className={`flex items-center gap-2.5 ${sidebarCollapsed ? 'justify-center' : 'justify-start'}`}>
          {/* Avatar */}
          <div className="user-avatar">
            <span>JD</span>
            <span className="user-online-dot" />
          </div>
          
          {!sidebarCollapsed && (
            <div className="flex flex-col min-w-0">
              <span className="user-name">John Doe</span>
              <span className="user-plan">PRO PLAN</span>
            </div>
          )}
        </div>
      </div>

    </aside>
  );
};
