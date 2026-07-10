import { invoke } from '@tauri-apps/api/core';

export const tauriCommands = {
  /** Start the Python FastAPI backend sidecar */
  startBackend: () => invoke<string>('start_backend'),

  /** Stop the Python backend */
  stopBackend: () => invoke<void>('stop_backend'),

  /** Check if backend is running */
  getBackendStatus: () => invoke<boolean>('get_backend_status'),

  /** Open native folder picker and return selected path */
  selectDirectory: () => invoke<string | null>('select_directory'),
};
