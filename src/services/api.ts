const API_BASE = 'http://127.0.0.1:8000';

type RequestMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';

async function request<T>(method: RequestMethod, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API Error ${res.status}: ${err}`);
  }
  
  return res.json() as Promise<T>;
}

// ── Health ──────────────────────────────────────────────────
export const api = {
  health: () => request<{ status: string }>('GET', '/health'),

  // ── Sessions ──────────────────────────────────────────────
  sessions: {
    create: (config: unknown) => request<{ id: string; name: string }>('POST', '/sessions', config),
    list: () => request<unknown[]>('GET', '/sessions'),
    get: (id: string) => request<unknown>('GET', `/sessions/${id}`),
    delete: (id: string) => request<void>('DELETE', `/sessions/${id}`),
  },

  // ── Providers ─────────────────────────────────────────────
  providers: {
    test: (config: unknown) => request<{ valid: boolean; error?: string }>('POST', '/providers/test', config),
    listModels: (config: unknown) => request<{ models: unknown[] }>('POST', '/providers/models', config),
  },
};
