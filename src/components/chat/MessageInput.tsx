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

  return (
    <div className="message-input-container p-4 glass-heavy border-t border-border-medium relative z-10">
      <div className="input-wrapper relative flex items-center">
        <textarea
          className="chat-textarea w-full bg-transparent border border-border-strong rounded-lg p-3 pr-12 text-primary resize-none glass-surface focus:outline-none focus:border-accent-cyan"
          rows={1}
          placeholder={isInterrupted ? "Waiting for approval..." : "Send a message or instruction..."}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!activeSessionId || isInterrupted}
          style={{ minHeight: '44px', maxHeight: '120px' }}
        />
        <button 
          className="send-button absolute right-2 bottom-2 w-8 h-8 rounded-md flex items-center justify-center text-primary disabled:opacity-50 disabled:cursor-not-allowed hover:bg-white/10 transition-colors"
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
