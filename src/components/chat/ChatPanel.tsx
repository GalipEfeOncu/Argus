import React from 'react';
import { useUIStore } from '@/stores/uiStore';
import { MessageList } from './MessageList';
import { MessageInput } from './MessageInput';
import { ApprovalBar } from './ApprovalBar';
import { SessionControls } from './SessionControls';
import type { SessionKind } from '@/types/session';
import './ChatPanel.css';

interface ChatPanelProps {
  sessionId: string;
  sessionName: string;
  projectName: string;
  sessionKind?: SessionKind;
  initialDraft?: string;
  onDraftChange?: (draft: string) => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({
  sessionId,
  sessionName,
  projectName,
  sessionKind = 'project',
  initialDraft,
  onDraftChange,
}) => {
  const { setActivePage, agentPanelVisible, toggleAgentPanel } = useUIStore();
  const isDirectChat = sessionKind === 'chat';

  return (
    <div className="chat-panel flex flex-col h-full">
      
      {/* ── Header / Breadcrumb ──────────────────────────── */}
      <div className="chat-header">
        
        {/* Left: back + breadcrumb */}
        <div className="chat-header-left">
          <button
            type="button"
            className="chat-back-btn"
            onClick={() => setActivePage('dashboard')}
            aria-label="Go to dashboard"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="19" y1="12" x2="5" y2="12" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
          </button>

          <nav className="chat-breadcrumb" aria-label={isDirectChat ? 'Chat breadcrumb' : 'Session breadcrumb'}>
            <button type="button" className="chat-breadcrumb-parent" onClick={() => setActivePage('dashboard')}>{projectName}</button>
            <span className="chat-breadcrumb-sep" aria-hidden="true">/</span>
            <span className="chat-breadcrumb-current" aria-current="page">{sessionName || 'Session'}</span>
          </nav>

          <span className="chat-env-badge">{isDirectChat ? 'CHAT' : 'LOCAL'}</span>
        </div>

        {/* Right: toggle agents + menu */}
        <div className="chat-header-right">
          <SessionControls sessionId={sessionId} />
          <button
            id="agent-panel-toggle"
            type="button"
            onClick={toggleAgentPanel}
            className={`chat-agents-toggle ${agentPanelVisible ? 'chat-agents-toggle--active' : ''}`}
            aria-controls="agent-context-panel"
            aria-expanded={agentPanelVisible}
            aria-label={`${agentPanelVisible ? 'Hide' : 'Open'} session context`}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
            <span>Agents</span>
          </button>

        </div>
      </div>

      {/* ── Message List ─────────────────────────────────── */}
      <div className="chat-messages-area flex-1 min-h-0 message-list-container">

        <MessageList sessionId={sessionId} sessionKind={sessionKind} />

      </div>

      {/* ── Bottom: Approval + Input ─────────────────────── */}
      <div className="chat-bottom-area">
        <ApprovalBar sessionId={sessionId} />
        <MessageInput sessionId={sessionId} sessionKind={sessionKind} initialDraft={initialDraft} onDraftChange={onDraftChange} />
      </div>
    </div>
  );
};
