import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AgentRole, ModelRef } from '@/types/agent';

interface SettingsState {
  defaultRoleModels: Partial<Record<AgentRole, ModelRef>>;
  defaultChatModel: ModelRef | null;
  manualProviderModels: ModelRef[];
  setDefaultRoleModel: (role: AgentRole, modelRef: ModelRef) => void;
  setDefaultChatModel: (modelRef: ModelRef) => void;
  addManualProviderModel: (modelRef: ModelRef) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      defaultRoleModels: {},
      defaultChatModel: null,
      manualProviderModels: [],

      setDefaultRoleModel: (role, modelRef) => {
        set((s) => ({ defaultRoleModels: { ...s.defaultRoleModels, [role]: modelRef } }));
      },
      setDefaultChatModel: (defaultChatModel) => set({ defaultChatModel }),
      addManualProviderModel: (modelRef) => set((state) => ({ manualProviderModels: state.manualProviderModels.some((item) => item.providerId === modelRef.providerId && item.modelId === modelRef.modelId) ? state.manualProviderModels : [...state.manualProviderModels, modelRef] })),

    }),
    {
      name: 'argus-settings',
      // Provider profiles live in the sidecar; credentials never enter this store.
      partialize: (state) => ({
        defaultRoleModels: state.defaultRoleModels,
        defaultChatModel: state.defaultChatModel,
        manualProviderModels: state.manualProviderModels,
      }),
    }
  )
);
