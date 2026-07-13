import React, { useEffect } from 'react';
import { useUIStore } from '@/stores/uiStore';
import { Sidebar } from '@/components/layout/Sidebar';
import { Header } from '@/components/layout/Header';
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
    // Kick off the backend — lib.rs already auto-starts it, but calling
    // invoke here lets the hook track the result and update status state.
    startBackend();
  }, [startBackend]);

  // ── Backend status banner ──────────────────────────────────────────────
  const banner = (() => {
    switch (status) {
      case 'starting':
        return (
          <div className="absolute top-2 right-1/2 translate-x-1/2 z-50 flex items-center gap-2 bg-accent-yellow/20 text-accent-yellow px-3 py-1 rounded-full text-xs border border-accent-yellow/50 backdrop-blur-md animate-pulse">
            <span className="w-1.5 h-1.5 rounded-full bg-accent-yellow inline-block" />
            Starting backend service…
          </div>
        );
      case 'error':
        return (
          <div
            className="absolute top-2 right-1/2 translate-x-1/2 z-50 flex items-center gap-2 bg-red-500/20 text-red-400 px-3 py-1 rounded-full text-xs border border-red-500/50 backdrop-blur-md cursor-pointer hover:bg-red-500/30 transition-colors"
            title={errorMsg ?? undefined}
            onClick={() => startBackend()}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-red-400 inline-block" />
            Backend error — click to retry
          </div>
        );
      case 'stopped':
        return (
          <div
            className="absolute top-2 right-1/2 translate-x-1/2 z-50 flex items-center gap-2 bg-gray-500/20 text-gray-400 px-3 py-1 rounded-full text-xs border border-gray-500/40 backdrop-blur-md cursor-pointer hover:bg-gray-500/30 transition-colors"
            onClick={() => startBackend()}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-gray-400 inline-block" />
            Backend stopped — click to start
          </div>
        );
      case 'running':
      default:
        return null; // No banner when everything is fine
    }
  })();

  return (
    <div className="app-container w-screen h-screen flex flex-col overflow-hidden bg-bg-base text-text-primary">
      {/* Background ambient glow */}
      <div className="absolute top-0 left-0 w-full h-full overflow-hidden pointer-events-none z-0">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-accent-cyan/10 blur-[120px]" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-accent-purple/10 blur-[120px]" />
      </div>

      <Header />
      
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
