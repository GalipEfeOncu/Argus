import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ProviderConfig } from '@/types/provider';
import type { AgentRole, ModelRef } from '@/types/agent';

interface SettingsState {
  providers: ProviderConfig[];
  defaultRoleModels: Partial<Record<AgentRole, ModelRef>>;
  useBuiltinFreeModels: boolean;
  addProvider: (config: Omit<ProviderConfig, 'id' | 'createdAt'>) => string;
  updateProvider: (id: string, updates: Partial<ProviderConfig>) => void;
  removeProvider: (id: string) => void;
  setDefaultRoleModel: (role: AgentRole, modelRef: ModelRef) => void;
  setUseBuiltinFreeModels: (val: boolean) => void;
  getProviderById: (id: string) => ProviderConfig | undefined;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      providers: [],
      defaultRoleModels: {},
      useBuiltinFreeModels: true,

      addProvider: (config) => {
        const id = crypto.randomUUID();
        const provider: ProviderConfig = { ...config, id, createdAt: Date.now() };
        set((s) => ({ providers: [...s.providers, provider] }));
        return id;
      },

      updateProvider: (id, updates) => {
        set((s) => ({
          providers: s.providers.map((p) => (p.id === id ? { ...p, ...updates } : p)),
        }));
      },

      removeProvider: (id) => {
        set((s) => ({ providers: s.providers.filter((p) => p.id !== id) }));
      },

      setDefaultRoleModel: (role, modelRef) => {
        set((s) => ({ defaultRoleModels: { ...s.defaultRoleModels, [role]: modelRef } }));
      },

      setUseBuiltinFreeModels: (val) => set({ useBuiltinFreeModels: val }),

      getProviderById: (id) => get().providers.find((p) => p.id === id),
    }),
    {
      name: 'argus-settings',
      // Don't persist API keys in plaintext in production - this is MVP, encrypt later
      partialize: (state) => ({
        providers: state.providers,
        defaultRoleModels: state.defaultRoleModels,
        useBuiltinFreeModels: state.useBuiltinFreeModels,
      }),
    }
  )
);
