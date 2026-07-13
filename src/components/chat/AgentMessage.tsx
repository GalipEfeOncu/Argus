import React from 'react';
import type { Message } from '@/types/agent';
import { AGENT_ROLE_META } from '@/types/agent';
import { formatRelativeTime } from '@/utils/formatters';
import { ToolCallBlock } from './ToolCallBlock';

interface AgentMessageProps {
  message: Message;
}

export const AgentMessage: React.FC<AgentMessageProps> = ({ message }) => {
  const isAgent = message.role === 'agent';
  
  // The mockup uses a specific background for the user vs agent
  const isUser = message.role === 'user';
  
  return (
    <div className={`flex w-full mb-4 px-6 ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[85%] rounded-md p-4 border ${
        isUser 
          ? 'bg-[var(--bg-element)] border-border-medium' 
          : 'bg-[var(--bg-card)] border-border-subtle'
      }`}>
        
        {/* Header Label */}
        <div className="flex items-center justify-between mb-2">
          <span className="text-muted text-xs uppercase tracking-widest font-medium">
            {isUser ? 'USER' : message.agentRole || 'AGENT'}
          </span>
        </div>

        {/* Message Body */}
        <div className="text-primary text-sm leading-relaxed whitespace-pre-wrap">
          {message.content && (
             <span>{message.content}</span>
          )}
          
          {message.isStreaming && <span className="inline-block w-1.5 h-3 ml-1 bg-muted animate-pulse"></span>}

          {message.toolCalls && message.toolCalls.length > 0 && (
            <div className="flex flex-col gap-2 mt-4">
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
