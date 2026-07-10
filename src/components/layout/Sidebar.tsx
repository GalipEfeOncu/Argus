import React from 'react';
import { useUIStore } from '@/stores/uiStore';
import './Sidebar.css';

export const Sidebar: React.FC = () => {
  const { activePage, setActivePage, sidebarCollapsed, toggleSidebar } = useUIStore();

  const navItems = [
    { id: 'dashboard', icon: '📊', label: 'Dashboard' },
    { id: 'session-setup', icon: '✨', label: 'New Session' },
    { id: 'history', icon: '🕒', label: 'History' },
    { id: 'settings', icon: '⚙️', label: 'Settings' },
  ] as const;

  return (
    <aside className={`sidebar flex flex-col glass-heavy border-r border-border-medium transition-all duration-300 ${sidebarCollapsed ? 'w-16' : 'w-64'}`}>
      <div className="sidebar-header p-4 flex items-center justify-between border-b border-border-subtle">
        {!sidebarCollapsed && (
          <div className="flex items-center gap-2">
            <span className="text-2xl">👁️</span>
            <h1 className="font-bold text-xl tracking-wider text-primary" style={{ textShadow: '0 0 10px rgba(0, 229, 255, 0.5)' }}>
              ARGUS
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

      <nav className="flex-1 py-4 flex flex-col gap-2 px-2">
        {navItems.map((item) => (
          <button
            key={item.id}
            onClick={() => setActivePage(item.id)}
            className={`nav-item flex items-center gap-3 p-3 rounded-md transition-all ${
              activePage === item.id 
                ? 'bg-white/10 text-accent-cyan shadow-[inset_2px_0_0_var(--accent-cyan)]' 
                : 'text-secondary hover:bg-white/5 hover:text-primary'
            } ${sidebarCollapsed ? 'justify-center' : 'justify-start'}`}
            title={sidebarCollapsed ? item.label : undefined}
          >
            <span className="text-xl">{item.icon}</span>
            {!sidebarCollapsed && <span className="font-medium text-sm">{item.label}</span>}
          </button>
        ))}
      </nav>

      <div className="sidebar-footer p-4 border-t border-border-subtle text-xs text-muted text-center">
        {!sidebarCollapsed ? 'Argus v0.1.0 MVP' : 'v0.1'}
      </div>
    </aside>
  );
};
