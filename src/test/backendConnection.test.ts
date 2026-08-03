import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ invoke: vi.fn(), isTauri: vi.fn(() => true) }));
vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke, isTauri: mocks.isTauri }));

import { authorizationHeaders, clearBackendConnection, ensureBackendConnection, restartBackendAfterCrash } from '@/services/backendConnection';

describe('native backend connection', () => {
  beforeEach(() => {
    clearBackendConnection();
    mocks.invoke.mockReset();
  });

  it('keeps the dynamic endpoint and access token in process memory', async () => {
    mocks.invoke.mockResolvedValue({
      baseUrl: 'http://127.0.0.1:43123',
      websocketUrl: 'ws://127.0.0.1:43123',
      accessToken: 'process-token',
      version: '0.1.0',
    });
    const connection = await ensureBackendConnection();
    expect(connection.baseUrl).toBe('http://127.0.0.1:43123');
    expect(authorizationHeaders(connection)).toEqual({ Authorization: 'Bearer process-token' });
    expect(mocks.invoke).toHaveBeenCalledTimes(1);
  });

  it('rejects a native endpoint that is not loopback', async () => {
    mocks.invoke.mockResolvedValue({
      baseUrl: 'https://example.invalid',
      websocketUrl: 'wss://example.invalid',
      accessToken: 'process-token',
      version: '0.1.0',
    });
    await expect(ensureBackendConnection()).rejects.toThrow('invalid connection');
  });

  it('starts a new generation after an idle-stop cache invalidation', async () => {
    mocks.invoke
      .mockResolvedValueOnce({ baseUrl: 'http://127.0.0.1:43123', websocketUrl: 'ws://127.0.0.1:43123', accessToken: 'first-token', version: '0.1.0' })
      .mockResolvedValueOnce({ baseUrl: 'http://127.0.0.1:43124', websocketUrl: 'ws://127.0.0.1:43124', accessToken: 'second-token', version: '0.1.0' });
    expect((await ensureBackendConnection()).accessToken).toBe('first-token');
    clearBackendConnection();
    expect((await ensureBackendConnection()).accessToken).toBe('second-token');
    expect(mocks.invoke).toHaveBeenCalledTimes(2);
  });

  it('waits out a failed readiness attempt before starting the crash generation', async () => {
    let rejectFirst: ((reason?: unknown) => void) | undefined;
    mocks.invoke
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectFirst = reject; }))
      .mockResolvedValueOnce({ baseUrl: 'http://127.0.0.1:43125', websocketUrl: 'ws://127.0.0.1:43125', accessToken: 'restart-token', version: '0.1.0' });
    const firstAttempt = ensureBackendConnection();
    const restarted = restartBackendAfterCrash();
    expect(mocks.invoke).toHaveBeenCalledTimes(1);
    rejectFirst?.(new Error('crashed before readiness'));
    await expect(firstAttempt).rejects.toThrow('crashed before readiness');
    expect((await restarted).accessToken).toBe('restart-token');
    expect(mocks.invoke).toHaveBeenCalledTimes(2);
  });
});
