import React from 'react';
import type { Message } from '@/types/agent';
import { ToolCallBlock } from './ToolCallBlock';
import './AgentMessage.css';

interface AgentMessageProps {
  message: Message;
}

export const AgentMessage: React.FC<AgentMessageProps> = ({ message }) => {
  const isUser = message.role === 'user';

  return (
    <div className={`message-row flex w-full mb-2 ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`message-bubble ${isUser ? 'user-bubble' : 'agent-bubble'}`}>

        {/* Header row */}
        <div className="message-bubble-header">
          <span className="message-role-label">
            {isUser ? 'You' : message.agentRole || 'Agent'}
          </span>
          <span className="message-time">
            {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        </div>

        {/* Body */}
        <div className="message-content">
          {message.content && <span>{message.content}</span>}

          {message.isStreaming && (
            <span className="streaming-cursor" />
          )}

          {message.toolCalls && message.toolCalls.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '12px' }}>
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
