import React from 'react';
import { useUIStore } from '@/stores/uiStore';
import { MessageList } from './MessageList';
import { MessageInput } from './MessageInput';
import { ApprovalBar } from './ApprovalBar';

interface ChatPanelProps {
  sessionId: string;
  sessionName: string;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ sessionId, sessionName }) => {
  const { setActivePage } = useUIStore();

  return (
    <div className="flex flex-col h-full bg-[var(--bg-main)]">
      {/* Header matching mockup */}
      <div className="flex justify-between items-center px-6 py-4 border-b border-border-subtle">
        <button 
          className="flex items-center gap-2 text-primary hover:text-secondary transition-colors"
          onClick={() => setActivePage('dashboard')}
        >
          <span className="text-muted text-lg">‹</span>
          <h2 className="font-medium">{sessionName || 'Session'}</h2>
        </button>
        
        <div className="flex items-center gap-2 text-sm text-muted">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--status-active)] animate-pulse" />
          Running
        </div>
      </div>
      
      {/* Message List Area */}
      <div className="flex-1 overflow-hidden relative">
        <MessageList />
      </div>

      {/* Bottom Area (Approval & Input) */}
      <div className="flex flex-col border-t border-border-subtle bg-[var(--bg-main)]">
        <ApprovalBar sessionId={sessionId} />
        <MessageInput sessionId={sessionId} />
      </div>
    </div>
  );
};
