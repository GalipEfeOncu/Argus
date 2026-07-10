import React from 'react';
import type { Message } from '@/types/agent';
import { AgentAvatar } from './AgentAvatar';
import { AGENT_ROLE_META } from '@/types/agent';
import { formatRelativeTime } from '@/utils/formatters';
import { ToolCallBlock } from './ToolCallBlock';
import './AgentMessage.css';

interface AgentMessageProps {
  message: Message;
}

export const AgentMessage: React.FC<AgentMessageProps> = ({ message }) => {
  const isAgent = message.role === 'agent';
  const roleMeta = isAgent && message.agentRole ? AGENT_ROLE_META[message.agentRole] : null;

  return (
    <div className={`message-wrapper message-${message.role}`}>
      <div className="message-avatar-container">
        {isAgent && message.agentRole ? (
          <AgentAvatar role={message.agentRole} isPulsing={message.isStreaming} />
        ) : (
          <div className="user-avatar">👤</div>
        )}
      </div>
      <div className="message-content-container">
        <div className="message-header flex items-center justify-between">
          <span
            className="message-author font-semibold"
            style={{ color: roleMeta ? `var(${roleMeta.colorVar})` : 'var(--text-primary)' }}
          >
            {roleMeta ? roleMeta.label : 'You'}
          </span>
          <span className="message-time text-xs text-muted">
            {formatRelativeTime(message.timestamp)}
          </span>
        </div>

        <div className="message-body text-base">
          {message.content && (
            <div className="message-text">
              {/* For a real app, use react-markdown here. Keeping simple for MVP */}
              <pre>{message.content}</pre>
            </div>
          )}
          
          {message.isStreaming && <span className="typing-cursor"></span>}

          {message.toolCalls && message.toolCalls.length > 0 && (
            <div className="message-tools flex-col gap-2 mt-3">
              {message.toolCalls.map((tc) => (
                <ToolCallBlock key={tc.id} toolCall={tc} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
