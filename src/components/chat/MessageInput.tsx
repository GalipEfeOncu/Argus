import React, { useState } from 'react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useAgentStore } from '@/stores/agentStore';
import { useSessionRoomStore } from '@/stores/sessionRoomStore';
import './MessageInput.css';

interface MessageInputProps {
  sessionId: string;
}

export const MessageInput: React.FC<MessageInputProps> = ({ sessionId }) => {
  const [content, setContent] = useState('');
  const { sendMessage, sendInterrupt } = useWebSocket(sessionId);
  const { isInterrupted } = useAgentStore();
  const projection = useSessionRoomStore((state) => state.projections[sessionId]);
  const isStreaming = Object.values(projection?.messages ?? {}).some((message) => message.streaming);
  const mentions = extractMentions(content);
  const targetLabel = mentions.length === 0 ? 'Coordinator' : mentions.join(', ');

  const handleSend = () => {
    if (!content.trim() || isInterrupted) return;
    sendMessage(content.trim(), mentions);
    setContent('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
    if (e.key === 'Escape' && isStreaming) {
      e.preventDefault();
      sendInterrupt();
    }
  };

  const isDisabled = isInterrupted;

  return (
    <div className="input-section">

      {/* ── Input Box ───────────────────────────────────── */}
      <div className="input-box-container">

        <textarea
          className="input-textarea"
          rows={3}
          aria-label="Message for shared room"
          placeholder={isInterrupted ? 'Waiting for approval…' : 'Describe your task; @name explicitly targets a participant'}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isDisabled}
        />

        {/* ── Bottom Row ──────────────────────────────────── */}
        <div className="input-bottom-row">

          {/* Execute button */}
          <button
            className="btn-execute"
            onClick={handleSend}
            disabled={!content.trim() || isInterrupted}
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

      <p className="composer-target">Targets: {targetLabel}{isStreaming ? ' · Escape interrupts active streaming' : ''}</p>

    </div>
  );
};

const knownMentionPattern = /@([a-z][a-z0-9_-]*)/gi;

export function extractMentions(content: string): string[] {
  const values = new Set<string>();
  for (const match of content.matchAll(knownMentionPattern)) values.add(match[1].toLowerCase());
  return [...values];
}
