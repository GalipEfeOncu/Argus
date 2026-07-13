import { create } from 'zustand';

type ActivePage = 'dashboard' | 'session-setup' | 'session' | 'settings' | 'history';

interface UIState {
  activePage: ActivePage;
  sidebarCollapsed: boolean;
  agentPanelVisible: boolean;
  workflowVisible: boolean;
  
  setActivePage: (page: ActivePage) => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (val: boolean) => void;
  toggleAgentPanel: () => void;
  toggleWorkflow: () => void;
}

export const useUIStore = create<UIState>()((set) => ({
  activePage: 'dashboard',
  sidebarCollapsed: false,
  agentPanelVisible: false,
  workflowVisible: true,

  setActivePage: (page) => set({ activePage: page }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setSidebarCollapsed: (val) => set({ sidebarCollapsed: val }),
  toggleAgentPanel: () => set((s) => ({ agentPanelVisible: !s.agentPanelVisible })),
  toggleWorkflow: () => set((s) => ({ workflowVisible: !s.workflowVisible })),
}));
