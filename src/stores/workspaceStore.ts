import { create } from 'zustand';
import type { ProjectSummary, SessionSummary } from '@/services/api';

interface WorkspaceStoreState {
  projects: ProjectSummary[];
  sessions: SessionSummary[];
  selectedProjectId: string | null;
  loading: boolean;
  loaded: boolean;
  error: string | null;
  beginLoad: () => void;
  finishLoad: (projects: ProjectSummary[] | null, sessions: SessionSummary[] | null, error?: string | null) => void;
  failLoad: (message: string) => void;
  invalidate: () => void;
  selectProject: (projectId: string | null) => void;
}

export const useWorkspaceStore = create<WorkspaceStoreState>()((set) => ({
  projects: [],
  sessions: [],
  selectedProjectId: null,
  loading: false,
  loaded: false,
  error: null,
  beginLoad: () => set({ loading: true, error: null }),
  finishLoad: (projects, sessions, error = null) => set((state) => ({
    projects: projects ?? state.projects,
    sessions: sessions ?? state.sessions,
    selectedProjectId: projects === null || (state.selectedProjectId !== null && projects.some((project) => project.id === state.selectedProjectId))
      ? state.selectedProjectId
      : null,
    loading: false,
    loaded: true,
    error,
  })),
  failLoad: (message) => set({ loading: false, loaded: true, error: message }),
  invalidate: () => set({ loaded: false }),
  selectProject: (selectedProjectId) => set({ selectedProjectId }),
}));
