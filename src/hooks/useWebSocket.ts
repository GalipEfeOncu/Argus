import { useEffect } from 'react';
import { wsManager } from '@/services/websocket';
import type { SessionConfigurationPatch } from '@/types/generated/session-commands';

export function useWebSocket(sessionId: string | null) {
  useEffect(() => {
    if (!sessionId) return;
    
    wsManager.connect(sessionId);
    return () => { wsManager.disconnect(); };
  }, [sessionId]);

  return {
    sendMessage: (content: string, mentionIds?: string[]) => wsManager.sendMessage(content, mentionIds),
    sendApproval: (approved: boolean, approvalId?: string) => wsManager.sendApproval(approved, approvalId),
    sendInterrupt: (participantId?: string) => wsManager.sendInterrupt(participantId),
    controlSession: (action: 'pause' | 'resume' | 'cancel') => wsManager.controlSession(action),
    updateConfiguration: (configurationVersion: number, patch: SessionConfigurationPatch, confirmConsequences?: boolean) => wsManager.updateConfiguration(configurationVersion, patch, confirmConsequences),
    resolveDecision: (decisionId: string, choice: 'reassign' | 'change_approach' | 'deliver_partial' | 'stop') => wsManager.resolveDecision(decisionId, choice),
  };
}
