import React from 'react';
import { useSessionRoomStore } from '@/stores/sessionRoomStore';
import { useWebSocket } from '@/hooks/useWebSocket';

export const SessionControls: React.FC<{ sessionId: string }> = ({ sessionId }) => {
  const projection = useSessionRoomStore((state) => state.projections[sessionId]);
  const { controlSession } = useWebSocket(sessionId);
  if (projection === undefined) return null;
  const recovering = projection.status === 'failed' && projection.lastError?.recoverable === true;
  const terminal = ['completed', 'completed_partial', 'cancelled'].includes(projection.status ?? '') || (projection.status === 'failed' && !recovering);
  const pending = Object.values(projection.pendingCommands).some((entry) => ['session.pause', 'session.resume', 'session.cancel'].includes(entry.command.type));
  const action = projection.status === 'paused' || recovering ? 'resume' : 'pause';
  return <div className="session-emergency-controls" aria-label="Always available session controls">
    <button type="button" onClick={() => controlSession(action)} disabled={terminal || pending}>{action === 'resume' ? 'Resume' : 'Pause'}</button>
    <button type="button" onClick={() => controlSession('cancel')} disabled={terminal || pending}>Cancel</button>
    {pending && <span role="status">Pending</span>}
  </div>;
};
