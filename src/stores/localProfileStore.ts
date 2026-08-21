import { create } from 'zustand';
import type { LocalProfile } from '@/services/api';

export type LocalProfileStatus = 'idle' | 'loading' | 'unconfigured' | 'ready' | 'saving' | 'error';

interface LocalProfileStoreState {
  profile: LocalProfile | null;
  status: LocalProfileStatus;
  error: string | null;
  beginLoad: () => void;
  finishLoad: (profile: LocalProfile | null) => void;
  beginSave: () => void;
  finishSave: (profile: LocalProfile) => void;
  fail: (message: string) => void;
}

export const useLocalProfileStore = create<LocalProfileStoreState>()((set) => ({
  profile: null,
  status: 'idle',
  error: null,
  beginLoad: () => set({ status: 'loading', error: null }),
  finishLoad: (profile) => set({ profile, status: profile === null ? 'unconfigured' : 'ready', error: null }),
  beginSave: () => set({ status: 'saving', error: null }),
  finishSave: (profile) => set({ profile, status: 'ready', error: null }),
  fail: (message) => set({ status: 'error', error: message }),
}));
