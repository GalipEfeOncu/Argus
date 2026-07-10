// ============================================================
// ARGUS — Provider & Model Type Definitions
// ============================================================

export type ProviderType = 'anthropic' | 'openai_compat' | 'google';

export interface ProviderConfig {
  id: string;
  name: string;
  type: ProviderType;
  apiKey: string;
  baseUrl?: string;       // Custom endpoint (OpenRouter, Ollama, etc.)
  isBuiltin?: boolean;    // Built-in free models
  isValid?: boolean;      // Last validation result
  models?: ModelInfo[];   // Fetched model list
  createdAt: number;
}

export interface ModelInfo {
  id: string;
  displayName: string;
  contextWindow?: number;
  supportsTools?: boolean;
  pricing?: {
    inputPerMillion: number;
    outputPerMillion: number;
  };
}

// Known built-in providers (for UI suggestions)
export const BUILTIN_PROVIDERS: Pick<ProviderConfig, 'name' | 'type' | 'baseUrl'>[] = [
  { name: 'Anthropic', type: 'anthropic' },
  { name: 'OpenAI', type: 'openai_compat' },
  { name: 'Google AI', type: 'google' },
  {
    name: 'OpenRouter',
    type: 'openai_compat',
    baseUrl: 'https://openrouter.ai/api/v1',
  },
  {
    name: 'Ollama (Local)',
    type: 'openai_compat',
    baseUrl: 'http://localhost:11434/v1',
  },
  {
    name: 'LM Studio (Local)',
    type: 'openai_compat',
    baseUrl: 'http://localhost:1234/v1',
  },
];

// Free built-in models (no API key required)
export const FREE_BUILTIN_MODELS: ModelInfo[] = [
  {
    id: 'gemini-2.0-flash',
    displayName: 'Gemini 2.0 Flash (Free)',
    contextWindow: 1_000_000,
    supportsTools: true,
  },
];
