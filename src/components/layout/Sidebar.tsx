import React from 'react';
import { useUIStore } from '@/stores/uiStore';
import './Sidebar.css';

export const Sidebar: React.FC = () => {
  const { activePage, setActivePage, sidebarCollapsed, toggleSidebar } = useUIStore();

  const navItems = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'session-setup', label: 'Sessions' }, // Updated label for consistency
    { id: 'history', label: 'History' },
    { id: 'settings', label: 'Settings' },
  ] as const;

  return (
    <aside className={`sidebar flex flex-col border-r border-border-subtle transition-all duration-200 ${sidebarCollapsed ? 'w-16' : 'w-[var(--sidebar-width)]'}`}>
      <div className="sidebar-header p-4 flex items-center justify-between">
        {!sidebarCollapsed && (
          <div className="flex items-center gap-2">
            <h1 className="font-bold text-lg tracking-wider text-primary">
              ARGUS<span className="text-accent-primary ml-1 text-sm">●</span>
            </h1>
          </div>
        )}
        <button 
          className="toggle-btn text-muted hover:text-primary transition-colors p-1"
          onClick={toggleSidebar}
        >
          {sidebarCollapsed ? '>>' : '<<'}
        </button>
      </div>

      <nav className="flex-1 py-4 flex flex-col gap-1 px-3">
        {navItems.map((item) => (
          <button
            key={item.id}
            onClick={() => setActivePage(item.id)}
            className={`nav-item flex items-center p-2 rounded-sm transition-colors ${
              activePage === item.id 
                ? 'active text-primary' 
                : 'text-secondary hover:text-primary'
            } ${sidebarCollapsed ? 'justify-center' : 'justify-start'}`}
            title={sidebarCollapsed ? item.label : undefined}
          >
            {!sidebarCollapsed && <span className="font-medium text-sm">{item.label}</span>}
            {sidebarCollapsed && <span className="font-medium text-xs">{item.label.substring(0, 1)}</span>}
          </button>
        ))}
      </nav>

      <div className="sidebar-footer p-4 text-xs text-muted">
        {!sidebarCollapsed ? 'small version' : 'v0.1'}
      </div>
    </aside>
  );
};
