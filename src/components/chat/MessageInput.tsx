import React, { useState } from 'react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useSessionStore } from '@/stores/sessionStore';
import { useAgentStore } from '@/stores/agentStore';

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

  return (
    <div className="px-6 pb-6 pt-2 bg-[var(--bg-main)]">
      <div className="relative flex items-center">
        <textarea
          className="w-full bg-[var(--bg-card)] border border-border-subtle rounded-md py-3 pl-4 pr-12 text-primary resize-none focus:outline-none focus:border-border-focus transition-colors"
          rows={1}
          placeholder={isInterrupted ? "Waiting for approval..." : "Message input"}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!activeSessionId || isInterrupted}
          style={{ minHeight: '48px', maxHeight: '120px' }}
        />
        <button 
          className="absolute right-3 bottom-3 w-6 h-6 flex items-center justify-center text-muted hover:text-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          onClick={handleSend}
          disabled={!content.trim() || isInterrupted}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
          </svg>
        </button>
      </div>
    </div>
  );
};
