import { create } from 'zustand';
import type { SessionProjection } from '@/services/sessionProjection';

type AnimationFrameHandle = number;

interface PendingStreamingProjection {
  projection: SessionProjection;
  frame: AnimationFrameHandle | null;
}

interface SessionRoomStoreState {
  projections: Record<string, SessionProjection>;
  streamingRenderCommits: number;
  publishProjection: (sessionId: string, projection: SessionProjection, isStreamingUpdate: boolean) => void;
  flushStreamingProjection: (sessionId: string) => void;
  clearProjection: (sessionId: string) => void;
}

const pendingStreaming = new Map<string, PendingStreamingProjection>();

function requestPaint(callback: FrameRequestCallback): AnimationFrameHandle {
  return typeof requestAnimationFrame === 'function'
    ? requestAnimationFrame(callback)
    : window.setTimeout(() => callback(Date.now()), 16);
}

function cancelPaint(handle: AnimationFrameHandle): void {
  if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(handle);
  else window.clearTimeout(handle);
}

/**
 * The room owns the render-facing copy of the canonical projection. Streaming
 * token updates are intentionally coalesced to one animation-frame commit;
 * ordered events themselves remain intact in SessionProjection.
 */
export const useSessionRoomStore = create<SessionRoomStoreState>()((set, get) => ({
  projections: {},
  streamingRenderCommits: 0,

  publishProjection: (sessionId, projection, isStreamingUpdate) => {
    if (!isStreamingUpdate) {
      const pending = pendingStreaming.get(sessionId);
      if (pending !== undefined) {
        if (pending.frame !== null) cancelPaint(pending.frame);
        pendingStreaming.delete(sessionId);
      }
      set((state) => ({ projections: { ...state.projections, [sessionId]: projection } }));
      return;
    }

    const pending = pendingStreaming.get(sessionId);
    if (pending !== undefined) {
      pending.projection = projection;
      return;
    }

    const next: PendingStreamingProjection = { projection, frame: null };
    next.frame = requestPaint(() => {
      // Browsers suspend animation frames in background tabs. Keep the most
      // recent projection until visibility returns even in timer fallbacks.
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
        const pending = pendingStreaming.get(sessionId);
        if (pending !== undefined) pending.frame = null;
        return;
      }
      get().flushStreamingProjection(sessionId);
    });
    pendingStreaming.set(sessionId, next);
  },

  flushStreamingProjection: (sessionId) => {
    const pending = pendingStreaming.get(sessionId);
    if (pending === undefined) return;
    pendingStreaming.delete(sessionId);
    set((state) => ({
      projections: { ...state.projections, [sessionId]: pending.projection },
      streamingRenderCommits: state.streamingRenderCommits + 1,
    }));
  },

  clearProjection: (sessionId) => {
    const pending = pendingStreaming.get(sessionId);
    if (pending?.frame !== null && pending !== undefined) cancelPaint(pending.frame);
    pendingStreaming.delete(sessionId);
    set((state) => {
      const { [sessionId]: _removed, ...projections } = state.projections;
      return { projections };
    });
  },
}));

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    for (const sessionId of pendingStreaming.keys()) {
      useSessionRoomStore.getState().flushStreamingProjection(sessionId);
    }
  });
}
