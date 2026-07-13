import React from 'react';
import { useSessionStore } from '@/stores/sessionStore';
import { ChatPanel } from '../chat/ChatPanel';
import { AgentPanel } from '../workflow/AgentPanel';
import './SessionView.css';

export const SessionView: React.FC = () => {
  const { getActiveSession } = useSessionStore();
  const session = getActiveSession();

  if (!session) {
    return (
      <div className="flex items-center justify-center h-full w-full text-muted bg-[var(--bg-main)]">
        No active session selected.
      </div>
    );
  }

  return (
    <div className="session-view w-full h-full flex overflow-hidden bg-[var(--bg-main)]">
      
      {/* Central Chat Panel (Left side of the view) */}
      <div className="flex-1 min-w-0 h-full relative z-10 flex flex-col">
        <ChatPanel sessionId={session.id} sessionName={session.name} />
      </div>

      {/* Right Sidebar (Agent Status & Workflow) */}
      <AgentPanel />
      
    </div>
  );
};
