import React from 'react';
import { MessageList } from './MessageList';
import { MessageInput } from './MessageInput';
import { ApprovalBar } from './ApprovalBar';
import './ChatPanel.css';

interface ChatPanelProps {
  sessionId: string;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ sessionId }) => {
  return (
    <div className="chat-panel flex flex-col h-full bg-bg-secondary relative overflow-hidden">
      <div className="chat-header p-3 border-b border-border-subtle flex justify-between items-center glass">
        <h3 className="font-semibold text-primary">Live Trace</h3>
        <div className="status-badge text-xs px-2 py-1 rounded bg-accent-cyan/10 text-accent-cyan border border-accent-cyan/20">
          Connected
        </div>
      </div>
      
      <div className="flex-1 overflow-hidden relative">
        <MessageList />
      </div>

      <div className="relative">
        <ApprovalBar sessionId={sessionId} />
        <MessageInput sessionId={sessionId} />
      </div>
    </div>
  );
};
