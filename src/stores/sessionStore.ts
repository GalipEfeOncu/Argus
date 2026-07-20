import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Session, SessionConfig, SessionConfiguration, SessionStatus } from '@/types/session';
import type { SessionConfigurationPatch } from '@/types/generated/session-commands';

interface SessionStoreState {
  sessions: Session[];
  activeSessionId: string | null;
  
  getActiveSession: () => Session | undefined;
  createSession: (config: SessionConfig) => string;
  updateSessionStatus: (id: string, status: SessionStatus) => void;
  patchSessionConfiguration: (id: string, patch: SessionConfigurationPatch) => void;
  setActiveSession: (id: string | null) => void;
  addMessageToSession: (sessionId: string, messageId: string) => void;
  deleteSession: (id: string) => void;
}

export const useSessionStore = create<SessionStoreState>()(
  persist(
    (set, get) => ({
      sessions: [],
      activeSessionId: null,

      getActiveSession: () => {
        const { sessions, activeSessionId } = get();
        return sessions.find((s) => s.id === activeSessionId);
      },

      createSession: (config) => {
        const id = crypto.randomUUID();
        const session: Session = {
          id,
          name: config.name ?? `Session #${Date.now()}`,
          projectPath: config.projectPath,
          task: config.task,
          status: 'setup',
          roleConfigs: config.roleConfigs,
          configuration: config.configuration,
          messages: [],
          startedAt: Date.now(),
          tokenUsage: { inputTokens: 0, outputTokens: 0, totalTokens: 0 },
        };
        set((s) => ({ sessions: [session, ...s.sessions], activeSessionId: id }));
        return id;
      },

      updateSessionStatus: (id, status) => {
        set((s) => ({
          sessions: s.sessions.map((session) =>
            session.id === id
              ? { ...session, status, completedAt: ['completed', 'completed_partial', 'cancelled', 'failed'].includes(status) ? Date.now() : session.completedAt }
              : session
          ),
        }));
      },

      patchSessionConfiguration: (id, patch) => set((state) => ({
        sessions: state.sessions.map((session) => {
          if (session.id !== id) return session;
          return {
            ...session,
            configuration: {
              ...session.configuration,
              ...(patch.availableAgentIds === undefined || patch.availableAgentIds === null ? {} : { availableAgentIds: patch.availableAgentIds }),
              ...(patch.requiredRoleRules === undefined || patch.requiredRoleRules === null ? {} : { requiredRoleRules: patch.requiredRoleRules.map((rule) => {
                const { capability, ...rest } = rule;
                return { ...rest, ...(capability === undefined || capability === null ? {} : { capability }) };
              }) }),
              approvalPolicy: {
                ...session.configuration.approvalPolicy,
                ...(patch.approvalBehavior === undefined || patch.approvalBehavior === null || patch.approvalBehavior === 'ask_each_time' ? {} : { behavior: patch.approvalBehavior }),
                ...(patch.limitResolution === undefined || patch.limitResolution === null ? {} : { limitResolution: patch.limitResolution }),
              },
            } as SessionConfiguration,
          };
        }),
      })),

      setActiveSession: (id) => set({ activeSessionId: id }),

      addMessageToSession: (_sessionId, _messageId) => {
        // Messages are tracked in agentStore for performance; session just tracks metadata
      },

      deleteSession: (id) => {
        set((s) => ({
          sessions: s.sessions.filter((session) => session.id !== id),
          activeSessionId: s.activeSessionId === id ? null : s.activeSessionId,
        }));
      },
    }),
    {
      name: 'argus-sessions',
      partialize: (state) => ({ sessions: state.sessions }),
    }
  )
);
