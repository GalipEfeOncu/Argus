import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Session, SessionConfig, SessionStatus } from '@/types/session';

interface SessionStoreState {
  sessions: Session[];
  activeSessionId: string | null;
  
  getActiveSession: () => Session | undefined;
  createSession: (config: SessionConfig) => string;
  updateSessionStatus: (id: string, status: SessionStatus) => void;
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
              ? { ...session, status, completedAt: status === 'completed' ? Date.now() : session.completedAt }
              : session
          ),
        }));
      },

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
