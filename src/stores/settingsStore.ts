import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AgentRole, ModelRef } from '@/types/agent';

interface SettingsState {
  defaultRoleModels: Partial<Record<AgentRole, ModelRef>>;
  manualProviderModels: ModelRef[];
  useBuiltinFreeModels: boolean;
  setDefaultRoleModel: (role: AgentRole, modelRef: ModelRef) => void;
  addManualProviderModel: (modelRef: ModelRef) => void;
  setUseBuiltinFreeModels: (val: boolean) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      defaultRoleModels: {},
      manualProviderModels: [],
      useBuiltinFreeModels: true,

      setDefaultRoleModel: (role, modelRef) => {
        set((s) => ({ defaultRoleModels: { ...s.defaultRoleModels, [role]: modelRef } }));
      },
      addManualProviderModel: (modelRef) => set((state) => ({ manualProviderModels: state.manualProviderModels.some((item) => item.providerId === modelRef.providerId && item.modelId === modelRef.modelId) ? state.manualProviderModels : [...state.manualProviderModels, modelRef] })),

      setUseBuiltinFreeModels: (val) => set({ useBuiltinFreeModels: val }),

    }),
    {
      name: 'argus-settings',
      // Provider profiles live in the sidecar; credentials never enter this store.
      partialize: (state) => ({
        defaultRoleModels: state.defaultRoleModels,
        manualProviderModels: state.manualProviderModels,
        useBuiltinFreeModels: state.useBuiltinFreeModels,
      }),
    }
  )
);
