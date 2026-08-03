import type { components, operations } from '@/types/generated/rest';
import { authorizationHeaders, ensureBackendConnection } from '@/services/backendConnection';

type RequestMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
type SessionCreateRequest = components['schemas']['SessionCreateRequest'];
type SessionCreateResponse = operations['create_session_sessions__post']['responses'][200]['content']['application/json'];
type SessionConfigurationResponse = operations['get_session_configuration_sessions__session_id__configuration_get']['responses'][200]['content']['application/json'];
type AgentDefinition = components['schemas']['AgentDefinitionResponse'];
type AgentDefinitionCreate = components['schemas']['AgentDefinitionCreate'];
type SkillPackage = components['schemas']['SkillPackageResponse'];
type ProviderProfile = components['schemas']['ProviderProfileResponse'];
type ProviderProfileCreate = components['schemas']['ProviderProfileCreate'];
type ProviderModels = components['schemas']['ProviderModelListResponse'];
type AcceptanceReview = components['schemas']['AcceptanceReviewResponse'];
type AcceptanceActionRequest = components['schemas']['AcceptanceActionRequest'];
type AcceptanceAction = components['schemas']['AcceptanceActionResponse'];
type AcceptancePatch = components['schemas']['AcceptancePatchResponse'];
type RuntimeHealth = operations['runtime_health_runtime_health_get']['responses'][200]['content']['application/json'];
type SupportBundle = operations['support_bundle_runtime_support_bundle_get']['responses'][200]['content']['application/json'];

async function request<T>(method: RequestMethod, path: string, body?: unknown): Promise<T> {
  const connection = await ensureBackendConnection();
  const res = await fetch(`${connection.baseUrl}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...authorizationHeaders(connection) },
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
  runtime: {
    health: () => request<RuntimeHealth>('GET', '/runtime/health'),
    supportBundle: (sessionIds: string[] = []) => request<SupportBundle>('GET', `/runtime/support-bundle${sessionIds.length === 0 ? '' : `?${sessionIds.map((id) => `session_id=${encodeURIComponent(id)}`).join('&')}`}`),
  },

  // ── Sessions ──────────────────────────────────────────────
  sessions: {
    create: (config: SessionCreateRequest) => request<SessionCreateResponse>('POST', '/sessions/', config),
    list: () => request<unknown[]>('GET', '/sessions'),
    get: (id: string) => request<unknown>('GET', `/sessions/${id}`),
    configuration: (id: string) => request<SessionConfigurationResponse>('GET', `/sessions/${id}/configuration`),
    delete: (id: string) => request<void>('DELETE', `/sessions/${id}`),
    acceptance: (id: string) => request<AcceptanceReview>('GET', `/sessions/${id}/acceptance`),
    acceptancePatch: (id: string) => request<AcceptancePatch>('GET', `/sessions/${id}/acceptance/patch`),
    acceptanceAction: (id: string, action: AcceptanceActionRequest) => request<AcceptanceAction>('POST', `/sessions/${id}/acceptance/actions`, action),
  },

  agentDefinitions: {
    list: () => request<AgentDefinition[]>('GET', '/agent-definitions/'),
    create: (definition: AgentDefinitionCreate) => request<AgentDefinition>('POST', '/agent-definitions/', definition),
  },

  skills: {
    list: () => request<SkillPackage[]>('GET', '/skills/'),
    import: (sourcePath: string) => request<SkillPackage>('POST', '/skills/import', { sourcePath }),
    setEnabled: (id: string, enabled: boolean) => request<SkillPackage>('POST', `/skills/${id}/enable`, { enabled }),
  },

  // ── Providers ─────────────────────────────────────────────
  providers: {
    list: () => request<ProviderProfile[]>('GET', '/providers/'),
    create: (profile: ProviderProfileCreate) => request<ProviderProfile>('POST', '/providers/', profile),
    remove: (id: string) => request<void>('DELETE', `/providers/${id}`),
    listModels: (id: string, manualModelId?: string) => request<ProviderModels>('POST', `/providers/${id}/models`, manualModelId ? { modelId: manualModelId } : undefined),
  },
};
