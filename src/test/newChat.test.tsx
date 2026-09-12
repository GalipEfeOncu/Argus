import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { NewChat } from '@/components/pages/NewChat';
import { useSessionStore } from '@/stores/sessionStore';
import { useSettingsStore } from '@/stores/settingsStore';
import { useUIStore } from '@/stores/uiStore';

const { listProviders, listModels, createChat, refreshProviderCredential } = vi.hoisted(() => ({
  listProviders: vi.fn(),
  listModels: vi.fn(),
  createChat: vi.fn(),
  refreshProviderCredential: vi.fn(),
}));

vi.mock('@/services/api', () => ({ api: {
  providers: { list: () => listProviders(), listModels: (...args: unknown[]) => listModels(...args) },
  sessions: { createChat: (...args: unknown[]) => createChat(...args) },
} }));

vi.mock('@/services/tauri', () => ({ tauriCommands: {
  refreshProviderCredential: (...args: unknown[]) => refreshProviderCredential(...args),
} }));

const provider = {
  id: 'provider-local', providerKind: 'openai' as const, displayName: 'Local OpenAI', endpoint: null,
  credentialConfigured: true, createdAtMs: 1, updatedAtMs: 1,
};

const model = { id: 'model-1', displayName: 'Model one', supportsTools: false, supportsStructuredOutput: false, source: 'catalog' as const };

beforeEach(() => {
  listProviders.mockReset();
  listModels.mockReset();
  createChat.mockReset();
  refreshProviderCredential.mockReset();
  refreshProviderCredential.mockResolvedValue(undefined);
  useUIStore.setState({ activePage: 'new-chat', newChatDraft: '', settingsReturnPage: null });
  useSettingsStore.setState({ defaultChatModel: null });
  useSessionStore.setState({ sessions: [], activeSessionId: null });
});

afterEach(cleanup);

test('keeps direct-chat drafting available and explains the provider gate', async () => {
  listProviders.mockResolvedValue([]);
  render(<NewChat />);

  expect(await screen.findByRole('alert')).toHaveTextContent('No provider configured');
  expect(screen.queryByRole('heading', { name: 'New chat' })).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'What would you like to talk about?' })).toBeInTheDocument();
  const textarea = screen.getByRole('textbox', { name: 'Message for direct chat' });
  fireEvent.change(textarea, { target: { value: 'Merhaba Argus' } });

  expect(textarea).toHaveValue('Merhaba Argus');
  expect(useUIStore.getState().newChatDraft).toBe('Merhaba Argus');
  expect(screen.getByRole('button', { name: /Send message/ })).toBeDisabled();

  fireEvent.click(screen.getByRole('button', { name: 'Open Provider Settings' }));
  expect(useUIStore.getState().activePage).toBe('settings');
  expect(useUIStore.getState().settingsReturnPage).toBe('new-chat');
});

test('creates a projectless chat with the selected provider model', async () => {
  listProviders.mockResolvedValue([provider]);
  listModels.mockResolvedValue({ models: [model] });
  createChat.mockResolvedValue({
    id: 'chat-1', name: 'New chat', sessionType: 'chat', projectId: null, goal: 'Direct conversation',
    agentSnapshots: [{ id: 'coordinator', sourceAgentId: 'coordinator', role: 'coordinator', name: 'Coordinator', modelBinding: { providerProfileId: provider.id, modelId: model.id } }],
    configurationVersion: 1, policyHash: 'policy', availableAgentIds: [], requiredRoleRules: [], executionLimits: {},
    approvalPolicy: {}, workspacePolicy: { mode: 'snapshot' }, acknowledgements: [],
  });
  render(<NewChat />);

  await waitFor(() => expect(createChat).toHaveBeenCalledWith(expect.objectContaining({ providerId: provider.id, modelId: model.id })));
  await waitFor(() => expect(useUIStore.getState().activePage).toBe('session'));
  expect(useSessionStore.getState().activeSessionId).toBe('chat-1');
  expect(useSessionStore.getState().sessions[0]?.kind).toBe('chat');
  expect(useSettingsStore.getState().defaultChatModel?.modelId).toBe(model.id);
});
