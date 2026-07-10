import React from 'react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useAgentStore } from '@/stores/agentStore';
import './ApprovalBar.css';

interface ApprovalBarProps {
  sessionId: string;
}

export const ApprovalBar: React.FC<ApprovalBarProps> = ({ sessionId }) => {
  const { isInterrupted, interruptReason, setInterrupted } = useAgentStore();
  const { sendApproval } = useWebSocket(sessionId);
  const [feedback, setFeedback] = React.useState('');

  if (!isInterrupted) return null;

  const handleApprove = () => {
    sendApproval(true, feedback);
    setInterrupted(false);
    setFeedback('');
  };

  const handleReject = () => {
    sendApproval(false, feedback);
    setInterrupted(false);
    setFeedback('');
  };

  return (
    <div className="approval-bar glass-heavy p-4 border-t border-border-medium shadow-xl">
      <div className="flex items-center gap-3 mb-3">
        <div className="warning-icon text-xl">⚠️</div>
        <div>
          <h4 className="text-primary font-semibold text-sm">Human Approval Required</h4>
          <p className="text-secondary text-xs">{interruptReason || 'The workflow requires your review.'}</p>
        </div>
      </div>
      
      <div className="flex flex-col gap-3">
        <input 
          type="text"
          className="feedback-input glass-surface p-2 text-sm rounded border border-border-subtle w-full"
          placeholder="Optional feedback or instructions..."
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
        />
        <div className="flex gap-2 justify-end">
          <button 
            className="btn btn-ghost text-sm px-4 py-2 rounded text-red-400 hover:bg-red-950/30"
            onClick={handleReject}
          >
            Reject & Revise
          </button>
          <button 
            className="btn btn-primary text-sm px-4 py-2 rounded bg-green-500/20 text-green-400 hover:bg-green-500/30 border border-green-500/30"
            onClick={handleApprove}
          >
            Approve & Continue
          </button>
        </div>
      </div>
    </div>
  );
};
