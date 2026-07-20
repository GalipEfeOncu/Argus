import React from 'react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useSessionRoomStore } from '@/stores/sessionRoomStore';
import './ApprovalBar.css';

interface ApprovalBarProps {
  sessionId: string;
}

export const ApprovalBar: React.FC<ApprovalBarProps> = ({ sessionId }) => {
  const projection = useSessionRoomStore((state) => state.projections[sessionId]);
  const { sendApproval } = useWebSocket(sessionId);
  const approvals = Object.values(projection?.approvals ?? {});

  if (approvals.length === 0) return null;

  return (
    <>
      {approvals.map((approval) => {
        const pending = Object.values(projection?.pendingCommands ?? {}).some((entry) => entry.command.type === 'approval.resolve' && entry.command.payload.approvalId === approval.id);
        return <div className="approval-bar" key={approval.id} role="status">
          <div className="approval-left">
            <div className="pulse-warning-dot" />
            <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
              <span className="approval-label">Approval required: {approval.capability}</span>
              <span className="approval-reason">{pending ? 'Decision pending — waiting for the session event.' : approval.scopeSummary}</span>
            </div>
          </div>
          <div className="approval-actions">
            <button className="btn-approve" onClick={() => sendApproval(true, approval.id)} disabled={pending}>Approve</button>
            <button className="btn-reject" onClick={() => sendApproval(false, approval.id)} disabled={pending}>Reject</button>
          </div>
        </div>;
      })}
    </>
  );
};
