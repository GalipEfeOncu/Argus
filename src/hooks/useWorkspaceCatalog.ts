import { useCallback, useEffect } from 'react';
import { api } from '@/services/api';
import { useWorkspaceStore } from '@/stores/workspaceStore';

let pendingLoad: Promise<void> | null = null;

export function useWorkspaceCatalog(): { refresh: () => Promise<void> } {
  const loaded = useWorkspaceStore((state) => state.loaded);
  const beginLoad = useWorkspaceStore((state) => state.beginLoad);
  const finishLoad = useWorkspaceStore((state) => state.finishLoad);
  const failLoad = useWorkspaceStore((state) => state.failLoad);

  const refresh = useCallback(async () => {
    if (pendingLoad !== null) return pendingLoad;
    beginLoad();
    pendingLoad = Promise.all([api.projects.list(), api.sessions.list()])
      .then(([projects, sessions]) => finishLoad(projects, sessions))
      .catch(() => failLoad('Local projects and sessions could not be loaded.'))
      .finally(() => { pendingLoad = null; });
    return pendingLoad;
  }, [beginLoad, failLoad, finishLoad]);

  useEffect(() => {
    if (!loaded) void refresh();
  }, [loaded, refresh]);

  return { refresh };
}
