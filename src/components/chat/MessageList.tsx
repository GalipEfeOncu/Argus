import React, { useEffect, useRef } from 'react';
import { useAgentStore } from '@/stores/agentStore';
import { AgentMessage } from './AgentMessage';
import './MessageList.css';

export const MessageList: React.FC = () => {
  const { messages } = useAgentStore();
  const endOfListRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Auto-scroll to bottom on new messages
    if (endOfListRef.current) {
      endOfListRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages.length, messages[messages.length - 1]?.isStreaming]);

  if (messages.length === 0) {
    return (
      <div className="empty-state flex flex-col items-center justify-center h-full text-muted">
        <span className="text-4xl mb-3 opacity-50">🤖</span>
        <p>No messages yet. Send a task to get started.</p>
      </div>
    );
  }

  return (
    <div className="message-list flex flex-col overflow-y-auto">
      {messages.map((msg) => (
        <AgentMessage key={msg.id} message={msg} />
      ))}
      <div ref={endOfListRef} className="h-4" />
    </div>
  );
};
