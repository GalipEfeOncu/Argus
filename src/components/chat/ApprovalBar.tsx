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

  if (!isInterrupted) return null;

  const handleApprove = () => {
    sendApproval(true, '');
    setInterrupted(false);
  };

  const handleReject = () => {
    sendApproval(false, '');
    setInterrupted(false);
  };

  return (
    <div className="approval-bar">
      <div className="approval-left">
        <div className="pulse-warning-dot" />
        <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <span className="approval-label">Attention Required</span>
          <span className="approval-reason">
            {interruptReason || 'Builder wants to execute: npm run test'}
          </span>
        </div>
      </div>

      <div className="approval-actions">
        <button className="btn-approve" onClick={handleApprove}>
          Approve
        </button>
        <button className="btn-reject" onClick={handleReject}>
          Reject
        </button>
      </div>
    </div>
  );
};
