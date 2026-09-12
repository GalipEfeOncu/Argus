import { create } from 'zustand';

export type ActivePage = 'dashboard' | 'new-chat' | 'new-session' | 'session-setup' | 'session' | 'settings' | 'profile';

interface UIState {
  activePage: ActivePage;
  newChatDraft: string;
  settingsReturnPage: ActivePage | null;
  sidebarCollapsed: boolean;
  agentPanelVisible: boolean;
  
  setActivePage: (page: ActivePage) => void;
  setNewChatDraft: (draft: string) => void;
  openSettings: (returnPage?: ActivePage | null) => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (val: boolean) => void;
  toggleAgentPanel: () => void;
  setAgentPanelVisible: (visible: boolean) => void;
}

export const useUIStore = create<UIState>()((set) => ({
  activePage: 'dashboard',
  newChatDraft: '',
  settingsReturnPage: null,
  sidebarCollapsed: false,
  agentPanelVisible: false,

  setActivePage: (activePage) => set({ activePage, settingsReturnPage: null }),
  setNewChatDraft: (newChatDraft) => set({ newChatDraft }),
  openSettings: (returnPage = null) => set({ activePage: 'settings', settingsReturnPage: returnPage }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setSidebarCollapsed: (val) => set({ sidebarCollapsed: val }),
  toggleAgentPanel: () => set((s) => ({ agentPanelVisible: !s.agentPanelVisible })),
  setAgentPanelVisible: (agentPanelVisible) => set({ agentPanelVisible }),
}));
