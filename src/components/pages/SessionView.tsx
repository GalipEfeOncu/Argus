import React from 'react';
import { useSessionStore } from '@/stores/sessionStore';
import { useUIStore } from '@/stores/uiStore';
import { ChatPanel } from '../chat/ChatPanel';
import { AgentPanel } from '../workflow/AgentPanel';
import './SessionView.css';

export const SessionView: React.FC = () => {
  const { getActiveSession } = useSessionStore();
  const { agentPanelVisible } = useUIStore();
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
      
      {/* Central Chat Panel (Left/middle side of the view) */}
      <div className="flex-1 min-w-0 h-full relative z-10 flex flex-col">
        <ChatPanel sessionId={session.id} sessionName={session.name} />
      </div>

      {/* Right Sidebar (Agent Status & Workflow) */}
      {agentPanelVisible && <AgentPanel sessionId={session.id} />}
      
    </div>
  );
};
