import React, { useEffect } from 'react';
import { useUIStore } from '@/stores/uiStore';
import { Sidebar } from '@/components/layout/Sidebar';
import { StatusBar } from '@/components/layout/StatusBar';
import { Dashboard } from '@/components/pages/Dashboard';
import { SessionSetup } from '@/components/pages/SessionSetup';
import { SessionView } from '@/components/pages/SessionView';
import { Settings } from '@/components/pages/Settings';
import { useTauri } from '@/hooks/useTauri';
import './App.css';

const PageRenderer: React.FC = () => {
  const { activePage } = useUIStore();
  
  switch (activePage) {
    case 'dashboard':     return <Dashboard />;
    case 'session-setup': return <SessionSetup />;
    case 'session':       return <SessionView />;
    case 'settings':      return <Settings />;
    case 'history':       return <div className="p-8 w-full flex items-center justify-center text-muted">History coming soon...</div>;
    default:              return <Dashboard />;
  }
};

const App: React.FC = () => {
  const { status, errorMsg, startBackend } = useTauri();

  useEffect(() => {
    startBackend();
  }, [startBackend]);

  const banner = (() => {
    switch (status) {
      case 'starting':
        return (
          <div className="absolute top-2 right-1/2 translate-x-1/2 z-50 flex items-center gap-2 bg-[var(--status-warning)] text-[#111111] px-3 py-1 rounded-full text-xs font-medium animate-pulse shadow-md">
            Starting backend service…
          </div>
        );
      case 'error':
        return (
          <div
            className="absolute top-2 right-1/2 translate-x-1/2 z-50 flex items-center gap-2 bg-[var(--status-error)] text-white px-3 py-1 rounded-full text-xs font-medium cursor-pointer shadow-md"
            title={errorMsg ?? undefined}
            onClick={() => startBackend()}
          >
            Backend error — click to retry
          </div>
        );
      case 'stopped':
        return (
          <div
            className="absolute top-2 right-1/2 translate-x-1/2 z-50 flex items-center gap-2 bg-[var(--status-idle)] text-white px-3 py-1 rounded-full text-xs font-medium cursor-pointer shadow-md"
            onClick={() => startBackend()}
          >
            Backend stopped — click to start
          </div>
        );
      case 'running':
      default:
        return null;
    }
  })();

  return (
    <div className="app-container w-screen h-screen flex flex-col overflow-hidden text-primary" style={{ backgroundColor: 'var(--bg-desktop)' }}>
      <div className="flex-1 flex overflow-hidden relative z-10">
        <Sidebar />
        <main className="flex-1 flex overflow-hidden relative">
          <PageRenderer />
        </main>
      </div>

      <StatusBar backendStatus={status} />

      {banner}
    </div>
  );
};

export default App;
