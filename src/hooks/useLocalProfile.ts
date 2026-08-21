import { useCallback, useEffect } from 'react';
import { api, type LocalProfile, type LocalProfilePatch } from '@/services/api';
import { useLocalProfileStore } from '@/stores/localProfileStore';

let pendingLoad: Promise<void> | null = null;

export function useLocalProfile(autoLoad = false): {
  refresh: () => Promise<void>;
  save: (patch: LocalProfilePatch) => Promise<LocalProfile>;
} {
  const beginLoad = useLocalProfileStore((state) => state.beginLoad);
  const finishLoad = useLocalProfileStore((state) => state.finishLoad);
  const beginSave = useLocalProfileStore((state) => state.beginSave);
  const finishSave = useLocalProfileStore((state) => state.finishSave);
  const fail = useLocalProfileStore((state) => state.fail);

  const refresh = useCallback(async () => {
    if (pendingLoad !== null) return pendingLoad;
    beginLoad();
    pendingLoad = api.profile.get()
      .then((state) => finishLoad(state.profile))
      .catch((cause: unknown) => {
        fail('Your local profile could not be loaded.');
        throw cause;
      })
      .finally(() => { pendingLoad = null; });
    return pendingLoad;
  }, [beginLoad, fail, finishLoad]);

  const save = useCallback(async (patch: LocalProfilePatch) => {
    beginSave();
    try {
      const profile = await api.profile.patch(patch);
      finishSave(profile);
      return profile;
    } catch (cause) {
      fail('Your local profile could not be saved. Your draft is still here.');
      throw cause;
    }
  }, [beginSave, fail, finishSave]);

  useEffect(() => {
    if (autoLoad) void refresh().catch(() => undefined);
  }, [autoLoad, refresh]);

  return { refresh, save };
}
