import { useEffect } from 'react';
import { wsManager } from '@/services/websocket';

export function useWebSocket(sessionId: string | null) {
  useEffect(() => {
    if (!sessionId) return;
    
    wsManager.connect(sessionId);
    return () => { wsManager.disconnect(); };
  }, [sessionId]);

  return {
    sendMessage: (content: string, mentionIds?: string[]) => wsManager.sendMessage(content, mentionIds),
    sendApproval: (approved: boolean, feedback?: string) => wsManager.sendApproval(approved, feedback),
    sendInterrupt: () => wsManager.sendInterrupt(),
  };
}
