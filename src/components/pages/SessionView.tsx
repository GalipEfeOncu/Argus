import React, { useEffect } from 'react';
import { useSessionStore } from '@/stores/sessionStore';
import { tauriCommands } from '@/services/tauri';
import { useUIStore } from '@/stores/uiStore';
import { useWorkspaceStore } from '@/stores/workspaceStore';
import { ChatPanel } from '../chat/ChatPanel';
import { AgentPanel } from '../workflow/AgentPanel';
import type { SessionKind } from '@/types/session';
import './SessionView.css';

export const SessionView: React.FC = () => {
  const { getActiveSession, activeSessionId } = useSessionStore();
  const { agentPanelVisible, newChatDraft, setNewChatDraft } = useUIStore();
  const localSession = getActiveSession();
  const durableSession = useWorkspaceStore((state) => state.sessions.find((session) => session.id === activeSessionId));
  const projects = useWorkspaceStore((state) => state.projects);
  const session = durableSession ?? localSession;
  const sessionKind: SessionKind = durableSession?.sessionType ?? localSession?.kind ?? 'project';
  const credentialProfileIds = [...new Set(
    localSession?.kind === 'chat'
      ? localSession.roleConfigs.map((config) => config.modelRef.providerId)
      : [],
  )];
  const credentialProfileKey = credentialProfileIds.join('|');

  useEffect(() => {
    if (sessionKind !== 'chat' || credentialProfileIds.length === 0) return;
    void Promise.all(credentialProfileIds.map((profileId) => tauriCommands.refreshProviderCredential(profileId).catch(() => undefined)));
  }, [credentialProfileKey, sessionKind]);

  if (!session) {
    return (
      <div className="session-view-empty" role="status">
        No active session selected.
      </div>
    );
  }

  const isDirectChat = sessionKind === 'chat';

  return (
    <div className="session-view w-full h-full flex overflow-hidden bg-[var(--bg-main)]">
      
      {/* Central Chat Panel (Left/middle side of the view) */}
      <div className="flex-1 min-w-0 h-full relative z-10 flex flex-col">
        <ChatPanel
          sessionId={session.id}
          sessionName={session.name}
          projectName={isDirectChat ? 'Local chat' : durableSession?.projectDisplayName
            ?? projects.find((project) => project.canonicalPath === localSession?.projectPath)?.displayName
            ?? localSession?.projectPath.split(/[\\/]/).filter(Boolean).at(-1)
            ?? 'Local project'}
          sessionKind={sessionKind}
          initialDraft={isDirectChat ? newChatDraft : undefined}
          onDraftChange={isDirectChat ? setNewChatDraft : undefined}
        />
      </div>

      {/* Right Sidebar (Agent Status & Workflow) */}
      {agentPanelVisible && <AgentPanel sessionId={session.id} />}
      
    </div>
  );
};
