import React from 'react';
import { useUIStore } from '@/stores/uiStore';
import { MessageList } from './MessageList';
import { MessageInput } from './MessageInput';
import { ApprovalBar } from './ApprovalBar';
import './ChatPanel.css';

interface ChatPanelProps {
  sessionId: string;
  sessionName: string;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ sessionId, sessionName }) => {
  const { setActivePage, agentPanelVisible, toggleAgentPanel } = useUIStore();

  return (
    <div className="chat-panel flex flex-col h-full">
      
      {/* ── Header / Breadcrumb ──────────────────────────── */}
      <div className="chat-header">
        
        {/* Left: back + breadcrumb */}
        <div className="chat-header-left">
          <button
            className="chat-back-btn"
            onClick={() => setActivePage('dashboard')}
            title="Go to Dashboard"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="19" y1="12" x2="5" y2="12" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
          </button>

          <div className="chat-breadcrumb">
            <span className="chat-breadcrumb-parent">argus-frontend</span>
            <span className="chat-breadcrumb-sep">/</span>
            <span className="chat-breadcrumb-current">{sessionName || 'Session'}</span>
          </div>

          <span className="chat-env-badge">LOCAL</span>
        </div>

        {/* Right: toggle agents + menu */}
        <div className="chat-header-right">
          <button
            onClick={toggleAgentPanel}
            className={`chat-agents-toggle ${agentPanelVisible ? 'chat-agents-toggle--active' : ''}`}
            title="Toggle Agents Panel"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
            <span>Agents</span>
          </button>

          <button className="chat-menu-btn" title="Session Options">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="5" r="1" />
              <circle cx="12" cy="12" r="1" />
              <circle cx="12" cy="19" r="1" />
            </svg>
          </button>
        </div>
      </div>

      {/* ── Message List ─────────────────────────────────── */}
      <div className="chat-messages-area flex-1 overflow-y-auto message-list-container">

        <MessageList />

        {/* AGENTS WORKING separator */}
        <div className="agents-working-separator">
          <div className="agents-working-line" />
          <div className="agents-working-pill">
            <span className="pulse-dot" />
            AGENTS WORKING
          </div>
          <div className="agents-working-line" />
        </div>

      </div>

      {/* ── Bottom: Approval + Input ─────────────────────── */}
      <div className="chat-bottom-area">
        <ApprovalBar sessionId={sessionId} />
        <MessageInput sessionId={sessionId} />
      </div>
    </div>
  );
};
