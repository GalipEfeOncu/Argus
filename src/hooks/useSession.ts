import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSessionStore } from '@/stores/sessionStore';
import { useAgentStore } from '@/stores/agentStore';
import { api } from '@/services/api';
import type { SessionConfig } from '@/types/session';
import type { AgentInfo } from '@/types/agent';

export function useSession() {
  const navigate = useNavigate();
  const sessionStore = useSessionStore();
  const agentStore = useAgentStore();

  const startSession = useCallback(async (config: SessionConfig) => {
    // Create session in backend
    const { id } = await api.sessions.create(config);
    
    // Create in local store
    sessionStore.createSession({ ...config });
    sessionStore.setActiveSession(id);

    // Initialize agents
    const agentInfos: AgentInfo[] = config.roleConfigs
      .filter((rc) => rc.enabled)
      .map((rc) => ({
        instanceId: rc.instanceId,
        role: rc.role,
        status: 'idle',
        modelRef: rc.modelRef,
        tokenCount: 0,
      }));
    agentStore.initAgents(agentInfos);

    navigate(`/session/${id}`);
  }, [navigate, sessionStore, agentStore]);

  const stopSession = useCallback((id: string) => {
    sessionStore.updateSessionStatus(id, 'completed');
    agentStore.clearSession();
  }, [sessionStore, agentStore]);

  return { startSession, stopSession };
}
