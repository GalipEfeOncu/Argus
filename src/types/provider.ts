// Non-secret provider settings. Credentials are held only by the native OS store.
export type ProviderType = 'openai' | 'anthropic' | 'openai_compat' | 'google';
export type ProviderPreset = 'openai' | 'anthropic' | 'google' | 'openrouter' | 'deepseek' | 'kimi' | 'xai' | 'mistral' | 'groq' | 'ollama' | 'custom';

export interface ProviderPresetOption {
  id: ProviderPreset;
  displayName: string;
  providerKind: ProviderType;
  endpoint: string | null;
  credentialRequired: boolean;
}

export interface ProviderProfile {
  id: string;
  providerKind: ProviderType;
  providerPreset: ProviderPreset;
  displayName: string;
  endpoint?: string | null;
  credentialConfigured: boolean;
  credentialRequired: boolean;
  createdAtMs: number;
  updatedAtMs: number;
}

export interface ModelInfo {
  id: string;
  displayName: string;
  contextWindow?: number | null;
  supportsTools?: boolean | null;
  supportsStructuredOutput?: boolean | null;
  supportsChat?: boolean | null;
  source: 'discovered' | 'catalog' | 'manual';
}

export const PROVIDER_PRESETS: ProviderPresetOption[] = [
  { id: 'openai', displayName: 'OpenAI', providerKind: 'openai', endpoint: null, credentialRequired: true },
  { id: 'anthropic', displayName: 'Anthropic', providerKind: 'anthropic', endpoint: null, credentialRequired: true },
  { id: 'google', displayName: 'Google Gemini', providerKind: 'google', endpoint: null, credentialRequired: true },
  { id: 'openrouter', displayName: 'OpenRouter', providerKind: 'openai_compat', endpoint: 'https://openrouter.ai/api/v1', credentialRequired: true },
  { id: 'deepseek', displayName: 'DeepSeek', providerKind: 'openai_compat', endpoint: 'https://api.deepseek.com', credentialRequired: true },
  { id: 'kimi', displayName: 'Moonshot / Kimi', providerKind: 'openai_compat', endpoint: 'https://api.moonshot.ai/v1', credentialRequired: true },
  { id: 'xai', displayName: 'xAI', providerKind: 'openai_compat', endpoint: 'https://api.x.ai/v1', credentialRequired: true },
  { id: 'mistral', displayName: 'Mistral AI', providerKind: 'openai_compat', endpoint: 'https://api.mistral.ai/v1', credentialRequired: true },
  { id: 'groq', displayName: 'Groq', providerKind: 'openai_compat', endpoint: 'https://api.groq.com/openai/v1', credentialRequired: true },
  { id: 'ollama', displayName: 'Ollama (Local)', providerKind: 'openai_compat', endpoint: 'http://localhost:11434/v1', credentialRequired: false },
  { id: 'custom', displayName: 'Custom OpenAI-compatible', providerKind: 'openai_compat', endpoint: null, credentialRequired: true },
];

// Kept as a compatibility alias for callers that only need preset labels.
export const BUILTIN_PROVIDERS = PROVIDER_PRESETS;
