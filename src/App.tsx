import React from 'react';
import { useUIStore } from '@/stores/uiStore';
import { Sidebar } from '@/components/layout/Sidebar';
import { StatusBar } from '@/components/layout/StatusBar';
import { Dashboard } from '@/components/pages/Dashboard';
import { SessionSetup } from '@/components/pages/SessionSetup';
import { Settings } from '@/components/pages/Settings';
import { Profile } from '@/components/pages/Profile';
import { useTauri } from '@/hooks/useTauri';
import { useLocalProfile } from '@/hooks/useLocalProfile';
import './App.css';

const SessionView = React.lazy(() => import('@/components/pages/SessionView')
  .then((module) => ({ default: module.SessionView })));

const SessionWorkspaceFallback: React.FC = () => (
  <div className="workspace-loading" role="status" aria-live="polite">
    Loading session workspace…
  </div>
);

const PageRenderer: React.FC = () => {
  const { activePage } = useUIStore();
  
  switch (activePage) {
    case 'dashboard':     return <Dashboard />;
    case 'session-setup': return <SessionSetup />;
    case 'session':       return <React.Suspense fallback={<SessionWorkspaceFallback />}><SessionView /></React.Suspense>;
    case 'settings':      return <Settings />;
    case 'profile':       return <Profile />;
    default:              return <Dashboard />;
  }
};

const App: React.FC = () => {
  const { status, errorMsg, startBackend } = useTauri();
  useLocalProfile(status === 'running');

  const banner = (() => {
    switch (status) {
      case 'starting':
        return (
          <div role="status" aria-live="polite" className="absolute top-2 right-1/2 translate-x-1/2 z-50 flex items-center gap-2 bg-[var(--status-warning)] text-[#111111] px-3 py-1 rounded-full text-xs font-medium animate-pulse shadow-md">
            Starting backend service…
          </div>
        );
      case 'error':
        return (
          <button
            type="button"
            className="absolute top-2 right-1/2 translate-x-1/2 z-50 flex items-center gap-2 bg-[var(--status-error)] text-[#111111] px-3 py-1 rounded-full text-xs font-medium cursor-pointer shadow-md"
            title={errorMsg ?? undefined}
            onClick={() => startBackend()}
          >
            Backend error — click to retry
          </button>
        );
      case 'stopped':
        return (
          <button
            type="button"
            className="absolute top-2 right-1/2 translate-x-1/2 z-50 flex items-center gap-2 bg-[var(--status-idle)] text-white px-3 py-1 rounded-full text-xs font-medium cursor-pointer shadow-md"
            onClick={() => startBackend()}
          >
            Backend stopped — click to start
          </button>
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
        <main className="workspace-main flex-1 flex overflow-hidden relative">
          <PageRenderer />
        </main>
      </div>

      <StatusBar backendStatus={status} />

      {banner}
    </div>
  );
};

export default App;
