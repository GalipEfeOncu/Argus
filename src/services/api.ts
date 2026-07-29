import type { components, operations } from '@/types/generated/rest';

const API_BASE = 'http://127.0.0.1:8000';

type RequestMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
type SessionCreateRequest = components['schemas']['SessionCreateRequest'];
type SessionCreateResponse = operations['create_session_sessions__post']['responses'][200]['content']['application/json'];
type SessionConfigurationResponse = operations['get_session_configuration_sessions__session_id__configuration_get']['responses'][200]['content']['application/json'];
type AgentDefinition = components['schemas']['AgentDefinitionResponse'];
type AgentDefinitionCreate = components['schemas']['AgentDefinitionCreate'];

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
    create: (config: SessionCreateRequest) => request<SessionCreateResponse>('POST', '/sessions/', config),
    list: () => request<unknown[]>('GET', '/sessions'),
    get: (id: string) => request<unknown>('GET', `/sessions/${id}`),
    configuration: (id: string) => request<SessionConfigurationResponse>('GET', `/sessions/${id}/configuration`),
    delete: (id: string) => request<void>('DELETE', `/sessions/${id}`),
  },

  agentDefinitions: {
    list: () => request<AgentDefinition[]>('GET', '/agent-definitions/'),
    create: (definition: AgentDefinitionCreate) => request<AgentDefinition>('POST', '/agent-definitions/', definition),
  },

  // ── Providers ─────────────────────────────────────────────
  providers: {
    test: (config: unknown) => request<{ valid: boolean; error?: string }>('POST', '/providers/test', config),
    listModels: (config: unknown) => request<{ models: unknown[] }>('POST', '/providers/models', config),
  },
};
