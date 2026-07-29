// Non-secret provider settings. Credentials are held only by the native OS store.
export type ProviderType = 'openai' | 'anthropic' | 'openai_compat' | 'google';

export interface ProviderProfile {
  id: string;
  providerKind: ProviderType;
  displayName: string;
  endpoint?: string | null;
  credentialConfigured: boolean;
  createdAtMs: number;
  updatedAtMs: number;
}

export interface ModelInfo {
  id: string;
  displayName: string;
  contextWindow?: number | null;
  supportsTools?: boolean | null;
  supportsStructuredOutput?: boolean | null;
  source: 'discovered' | 'catalog' | 'manual';
}

export const BUILTIN_PROVIDERS: Pick<ProviderProfile, 'displayName' | 'providerKind' | 'endpoint'>[] = [
  { displayName: 'OpenAI', providerKind: 'openai' },
  { displayName: 'Anthropic', providerKind: 'anthropic' },
  { displayName: 'Google AI', providerKind: 'google' },
  { displayName: 'OpenRouter', providerKind: 'openai_compat', endpoint: 'https://openrouter.ai/api/v1' },
  { displayName: 'Ollama (Local)', providerKind: 'openai_compat', endpoint: 'http://localhost:11434/v1' },
];
