import { useState, useCallback, useEffect, useRef } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-dialog';
import { listen } from '@tauri-apps/api/event';
import { authorizationHeaders, clearBackendConnection, ensureBackendConnection, restartBackendAfterCrash } from '@/services/backendConnection';

export type BackendStatus = 'starting' | 'running' | 'stopped' | 'error';

export function useTauri() {
  const [status, setStatus] = useState<BackendStatus>('stopped');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Health poll ────────────────────────────────────────────────────────────
  // Polls /health every 2 s until the backend responds with 200.
  // Started immediately when the app boots so we catch backends that were
  // already running (e.g. developer started manually) without waiting for
  // the invoke to complete.
  const startHealthPoll = useCallback(() => {
    if (pollRef.current) return; // already polling
    pollRef.current = setInterval(async () => {
      try {
        const connection = await ensureBackendConnection();
        const res = await fetch(`${connection.baseUrl}/health`, { headers: authorizationHeaders(connection) });
        if (res.ok) {
          setStatus('running');
          setErrorMsg(null);
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }
      } catch {
        // Backend not yet up — keep polling silently.
      }
    }, 2000);
  }, []);

  const stopHealthPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // ── Start backend ──────────────────────────────────────────────────────────
  const startBackend = useCallback(async () => {
    setStatus('starting');
    setErrorMsg(null);

    // Start health polling immediately — independent of the invoke result.
    // This way the UI updates as soon as the port is reachable, even if the
    // invoke is still blocking (it waits up to 20 s on the Rust side).
    startHealthPoll();

    try {
      const result = await ensureBackendConnection();
      // Rust side already waited for the port to be reachable before
      // returning "started".  If we're here, the backend is up.
      if (result.baseUrl.startsWith('http://127.0.0.1:')) {
        setStatus('running');
        setErrorMsg(null);
        stopHealthPoll(); // no need to keep polling
      }
    } catch (e) {
      // Rust returned Err — backend failed to start.
      console.error('[useTauri] start_backend failed:', e);
      setErrorMsg(String(e));
      setStatus('error');
      stopHealthPoll();
    }
  }, [startHealthPoll, stopHealthPoll]);

  useEffect(() => {
    let disposed = false;
    let unlistenCrash: (() => void) | null = null;
    let unlistenExhausted: (() => void) | null = null;
    let unlistenStopped: (() => void) | null = null;
    const markReady = () => setStatus('running');
    window.addEventListener('argus:sidecar-ready', markReady);
    void listen<number>('argus://sidecar-crashed', () => {
      clearBackendConnection();
      if (disposed) return;
      setStatus('starting');
      void restartBackendAfterCrash().then(() => {
        if (!disposed) setStatus('running');
      }).catch((error: unknown) => {
        if (!disposed) {
          setErrorMsg(String(error));
          setStatus('error');
        }
      });
    }).then((stopListening) => { unlistenCrash = stopListening; }).catch(() => undefined);
    void listen<number>('argus://sidecar-crash-exhausted', () => {
      clearBackendConnection();
      if (!disposed) {
        setErrorMsg('The backend stopped after repeated quick crashes. Click to retry.');
        setStatus('error');
      }
    }).then((stopListening) => { unlistenExhausted = stopListening; }).catch(() => undefined);
    void listen<string>('argus://sidecar-stopped', () => {
      clearBackendConnection();
      if (!disposed) setStatus('stopped');
    }).then((stopListening) => { unlistenStopped = stopListening; }).catch(() => undefined);
    return () => {
      disposed = true;
      window.removeEventListener('argus:sidecar-ready', markReady);
      unlistenCrash?.();
      unlistenExhausted?.();
      unlistenStopped?.();
      stopHealthPoll();
    };
  }, [startBackend, stopHealthPoll]);

  // ── Stop backend ───────────────────────────────────────────────────────────
  const stopBackend = useCallback(async () => {
    stopHealthPoll();
    try {
      await invoke('stop_backend');
      clearBackendConnection();
      setStatus('stopped');
    } catch (e) {
      console.error('[useTauri] stop_backend invoke failed:', e);
    }
  }, [stopHealthPoll]);

  // ── Open directory dialog ──────────────────────────────────────────────────
  const openDirectoryDialog = useCallback(async (): Promise<string | null> => {
    try {
      const selectedPath = await open({ directory: true, multiple: false });
      return selectedPath as string | null;
    } catch (e) {
      console.error('[useTauri] openDirectoryDialog failed:', e);
      return null;
    }
  }, []);

  const isRunning = status === 'running';

  return {
    status,
    isRunning,
    errorMsg,
    startBackend,
    stopBackend,
    openDirectoryDialog,
  };
}
