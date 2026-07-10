import { useState, useCallback } from 'react';
import { open } from '@tauri-apps/plugin-dialog';

export function useTauri() {
  const [isRunning, setIsRunning] = useState(false);

  const startBackend = useCallback(async () => {
    try {
      // Assuming a backend start command is defined in Rust
      // await invoke('start_backend');
      setIsRunning(true);
    } catch (e) {
      console.error('Failed to start backend', e);
    }
  }, []);

  const openDirectoryDialog = useCallback(async (): Promise<string | null> => {
    try {
      const selectedPath = await open({
        directory: true,
        multiple: false,
      });
      return selectedPath as string | null;
    } catch (e) {
      console.error('Failed to open dialog', e);
      return null;
    }
  }, []);

  return {
    isRunning,
    startBackend,
    openDirectoryDialog,
  };
}
