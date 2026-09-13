import type { components, operations } from '@/types/generated/rest';
import { authorizationHeaders, ensureBackendConnection } from '@/services/backendConnection';

type RequestMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
export type SessionCreateRequest = components['schemas']['SessionCreateRequest'];
export type SessionCreateResponse = operations['create_session_sessions__post']['responses'][200]['content']['application/json'];
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
export type LocalProfile = components['schemas']['LocalProfileResponse'];
export type LocalProfilePatch = components['schemas']['LocalProfilePatch'];
type LocalProfileState = components['schemas']['LocalProfileStateResponse'];
export type ProjectSummary = components['schemas']['ProjectResponse'];
export type SessionSummary = components['schemas']['SessionSummaryResponse'];
export type SessionDetail = components['schemas']['SessionDetailResponse'];

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

  profile: {
    get: () => request<LocalProfileState>('GET', '/profile'),
    patch: (profile: LocalProfilePatch) => request<LocalProfile>('PATCH', '/profile', profile),
  },

  projects: {
    list: () => request<ProjectSummary[]>('GET', '/projects/'),
  },

  // ── Sessions ──────────────────────────────────────────────
  sessions: {
    create: (config: SessionCreateRequest) => request<SessionCreateResponse>('POST', '/sessions/', config),
    createChat: (model: { providerId: string; modelId: string }) => request<SessionCreateResponse>('POST', '/sessions/', {
      sessionType: 'chat',
      name: 'New chat',
      goal: 'Direct conversation',
      coordinatorAgentId: 'coordinator',
      agents: [{
        id: 'coordinator',
        role: 'coordinator',
        modelBinding: { providerProfileId: model.providerId, modelId: model.modelId },
        systemPrompt: 'You are Argus, a concise general assistant. Answer directly in the user’s language. Do not repeat introductions or generic capability lists unless asked. Do not claim to have used tools or changed files.',
      }],
      configuration: { availableAgentIds: [], workspacePolicy: { mode: 'snapshot' } },
      workspaceMode: 'snapshot',
      acknowledgeDirectWrite: false,
    }),
    list: () => request<SessionSummary[]>('GET', '/sessions/'),
    get: (id: string) => request<SessionDetail>('GET', `/sessions/${id}`),
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
