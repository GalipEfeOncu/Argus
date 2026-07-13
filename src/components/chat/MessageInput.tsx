import React, { useState } from 'react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useSessionStore } from '@/stores/sessionStore';
import { useAgentStore } from '@/stores/agentStore';
import './MessageInput.css';

interface MessageInputProps {
  sessionId: string;
}

export const MessageInput: React.FC<MessageInputProps> = ({ sessionId }) => {
  const [content, setContent] = useState('');
  const { sendMessage } = useWebSocket(sessionId);
  const { activeSessionId } = useSessionStore();
  const { isInterrupted } = useAgentStore();

  const handleSend = () => {
    if (!content.trim() || isInterrupted) return;
    sendMessage(content);
    setContent('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const isDisabled = !activeSessionId || isInterrupted;

  return (
    <div className="input-section">

      {/* ── Input Box ───────────────────────────────────── */}
      <div className="input-box-container">

        <textarea
          className="input-textarea"
          rows={3}
          placeholder={isInterrupted ? 'Waiting for approval…' : 'Describe your task, / for agent roles, @ for project context'}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isDisabled}
        />

        {/* ── Bottom Row ──────────────────────────────────── */}
        <div className="input-bottom-row">

          {/* Left actions */}
          <div className="input-left-actions">

            {/* Add context */}
            <button className="input-action-btn" title="Add context" type="button">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            </button>

            {/* Mode pill */}
            <div className="mode-selector-pill">
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3M4.22 19.78l2.12-2.12M17.66 6.34l2.12-2.12" />
              </svg>
              Multi-Agent · Auto
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <rect x="3" y="11" width="18" height="11" rx="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
            </div>

            {/* Microphone */}
            <button className="input-action-btn" title="Voice input" type="button">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
            </button>
          </div>

          {/* Execute button */}
          <button
            className="btn-execute"
            onClick={handleSend}
            disabled={!content.trim() || isInterrupted || !activeSessionId}
            type="button"
          >
            <span>Execute Task</span>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polyline points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
      </div>

      {/* ── Sub pills ───────────────────────────────────── */}
      <div className="input-sub-pills">
        <div className="sub-pill">
          New Task
          <span className="sub-pill-kbd">⇧Tab</span>
        </div>
        <div className="sub-pill">Multitask</div>
      </div>

    </div>
  );
};
