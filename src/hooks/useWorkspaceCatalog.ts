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
    pendingLoad = Promise.allSettled([api.projects.list(), api.sessions.list()])
      .then(([projectsResult, sessionsResult]) => {
        const projects = projectsResult.status === 'fulfilled' ? projectsResult.value : null;
        const sessions = sessionsResult.status === 'fulfilled' ? sessionsResult.value : null;
        if (projects === null && sessions === null) {
          failLoad('Local projects and sessions could not be loaded.');
          return;
        }
        const error = projects === null
          ? 'Local projects could not be refreshed. Previously loaded projects remain available.'
          : sessions === null
            ? 'Local sessions could not be refreshed. Previously loaded sessions remain available.'
            : null;
        finishLoad(projects, sessions, error);
      })
      .finally(() => { pendingLoad = null; });
    return pendingLoad;
  }, [beginLoad, failLoad, finishLoad]);

  useEffect(() => {
    if (!loaded) void refresh();
  }, [loaded, refresh]);

  return { refresh };
}
