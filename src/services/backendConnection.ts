import { invoke, isTauri } from '@tauri-apps/api/core';

export interface BackendConnection {
  baseUrl: string;
  websocketUrl: string;
  accessToken: string;
  version: string;
}

const developmentConnection: BackendConnection = {
  baseUrl: 'http://127.0.0.1:8000',
  websocketUrl: 'ws://127.0.0.1:8000',
  accessToken: '',
  version: '0.1.0',
};

let current: BackendConnection | null = null;
let pending: Promise<BackendConnection> | null = null;

function validConnection(value: unknown): value is BackendConnection {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.baseUrl === 'string'
    && /^http:\/\/127\.0\.0\.1:\d+$/.test(candidate.baseUrl)
    && typeof candidate.websocketUrl === 'string'
    && /^ws:\/\/127\.0\.0\.1:\d+$/.test(candidate.websocketUrl)
    && typeof candidate.accessToken === 'string'
    && candidate.accessToken.length > 0
    && typeof candidate.version === 'string';
}

export async function ensureBackendConnection(): Promise<BackendConnection> {
  if (current !== null) return current;
  if (pending !== null) return pending;
  pending = (async (): Promise<BackendConnection> => {
    let value: unknown;
    try {
      value = await invoke<unknown>('start_backend');
    } catch (error: unknown) {
      if (import.meta.env.DEV && !isTauri()) {
        value = developmentConnection;
      } else {
        throw error;
      }
    }
    if (value === developmentConnection) {
      current = developmentConnection;
      return developmentConnection;
    }
    if (!validConnection(value)) throw new Error('The native backend returned an invalid connection.');
    current = value;
    window.dispatchEvent(new Event('argus:sidecar-ready'));
    return value;
  })().finally(() => { pending = null; });
  return pending;
}

export function clearBackendConnection(): void {
  current = null;
}

export async function restartBackendAfterCrash(): Promise<BackendConnection> {
  current = null;
  const activeAttempt = pending;
  if (activeAttempt !== null) {
    await activeAttempt.catch(() => undefined);
  }
  current = null;
  return ensureBackendConnection();
}

export function authorizationHeaders(connection: BackendConnection): Record<string, string> {
  return connection.accessToken.length === 0 ? {} : { Authorization: `Bearer ${connection.accessToken}` };
}
