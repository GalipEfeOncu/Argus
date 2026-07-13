import React from 'react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useAgentStore } from '@/stores/agentStore';

interface ApprovalBarProps {
  sessionId: string;
}

export const ApprovalBar: React.FC<ApprovalBarProps> = ({ sessionId }) => {
  const { isInterrupted, interruptReason, setInterrupted } = useAgentStore();
  const { sendApproval } = useWebSocket(sessionId);

  // Mocking interrupt for UI overhaul preview if not interrupted yet
  // In real app, only show if isInterrupted is true.
  // For now, we always render it to match the mockup, but wrapped in a check.
  const showMock = true; // Set to false in Phase 1.2
  
  if (!isInterrupted && !showMock) return null;

  const handleApprove = () => {
    sendApproval(true, '');
    setInterrupted(false);
  };

  const handleReject = () => {
    sendApproval(false, '');
    setInterrupted(false);
  };

  return (
    <div className="flex items-center justify-between p-4 bg-[var(--bg-card)] border border-border-subtle rounded-md mx-6 mb-4">
      <div className="text-sm text-primary">
        {interruptReason || 'Builder wants to execute: npm install'}
      </div>
      
      <div className="flex gap-2">
        <button 
          className="text-xs px-3 py-1.5 rounded bg-accent-primary text-primary hover:bg-accent-hover transition-colors font-medium"
          onClick={handleApprove}
        >
          [Approve]
        </button>
        <button 
          className="text-xs px-3 py-1.5 rounded border border-accent-primary text-accent-primary hover:bg-accent-transparent transition-colors font-medium"
          onClick={handleReject}
        >
          [Reject]
        </button>
      </div>
    </div>
  );
};
