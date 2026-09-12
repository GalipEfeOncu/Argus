import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Settings } from '@/components/pages/Settings';
import { useSettingsStore } from '@/stores/settingsStore';
import { useUIStore } from '@/stores/uiStore';

const { listProviders, listModels } = vi.hoisted(() => ({ listProviders: vi.fn(), listModels: vi.fn() }));

vi.mock('@/services/api', () => ({ api: { providers: {
  list: () => listProviders(),
  listModels: (...args: unknown[]) => listModels(...args),
  create: vi.fn(),
  remove: vi.fn(),
} } }));

vi.mock('@/services/tauri', () => ({ tauriCommands: {
  refreshProviderCredential: vi.fn().mockResolvedValue(undefined),
  storeProviderCredential: vi.fn(),
  deleteProviderCredential: vi.fn(),
  removeProviderCredential: vi.fn(),
} }));

const provider = {
  id: 'provider-local', providerKind: 'openai' as const, displayName: 'Local provider', endpoint: null,
  credentialConfigured: false, createdAtMs: 1, updatedAtMs: 1,
};

beforeEach(() => {
  listProviders.mockReset();
  listModels.mockReset();
  useUIStore.setState({ activePage: 'settings', settingsReturnPage: null, newChatDraft: '' });
});

afterEach(cleanup);

test('provider catalogue loading failures show a normalized retry state', async () => {
  listProviders.mockRejectedValueOnce(new Error('credential=should-not-render')).mockResolvedValueOnce([]);
  render(<Settings />);

  expect(screen.getByRole('heading', { name: 'Provider Settings' })).toBeInTheDocument();
  expect(screen.getByText('Manage provider credentials and discover available models.')).toBeInTheDocument();
  expect(screen.queryByText(/agent configuration/i)).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('Loading configured providers');
  expect(await screen.findByRole('alert')).toHaveTextContent('Configured providers could not be loaded');
  expect(screen.queryByText(/credential=should-not-render/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Retry providers' }));
  await waitFor(() => expect(listProviders).toHaveBeenCalledTimes(2));
  expect(await screen.findByText('No providers configured yet.')).toBeInTheDocument();
});

test('one provider model failure keeps its provider visible and supports a bounded retry', async () => {
  listProviders.mockResolvedValue([provider]);
  listModels.mockRejectedValueOnce(new Error('raw SDK body')).mockResolvedValueOnce({
    models: [{ id: 'model-1', displayName: 'Model one', supportsTools: true, supportsStructuredOutput: true, source: 'catalog' }],
  });
  render(<Settings />);

  expect(await screen.findByText('Local provider')).toBeInTheDocument();
  expect(await screen.findByRole('alert')).toHaveTextContent('Model catalogue unavailable');
  expect(screen.queryByText('raw SDK body')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Retry models' }));
  expect(await screen.findByText(/Model one · tools supported/)).toBeInTheDocument();
  expect(listModels).toHaveBeenCalledTimes(2);
});

test('searches the discovered catalogue and selects a model for chat', async () => {
  listProviders.mockResolvedValue([{
    ...provider, providerPreset: 'ollama', credentialRequired: false,
  }]);
  listModels.mockResolvedValue({ models: [
    { id: 'llama3.2:3b', displayName: 'Llama 3.2 3B', supportsChat: true, source: 'discovered' },
    { id: 'nomic-embed-text', displayName: 'Nomic Embed Text', supportsChat: false, source: 'discovered' },
  ] });
  useSettingsStore.setState({ defaultChatModel: null });
  render(<Settings />);

  expect(await screen.findByText(/Llama 3\.2 3B/)).toBeInTheDocument();
  const search = screen.getByRole('textbox', { name: 'Local provider model search' });
  fireEvent.change(search, { target: { value: 'llama' } });
  expect(screen.queryByText(/Nomic Embed Text/)).not.toBeInTheDocument();
  const useForChat = screen.getAllByRole('button', { name: 'Use for chat' }).find((button) => !button.hasAttribute('disabled'));
  expect(useForChat).toBeDefined();
  fireEvent.click(useForChat as HTMLButtonElement);

  expect(useSettingsStore.getState().defaultChatModel).toMatchObject({
    providerId: 'provider-local', modelId: 'llama3.2:3b',
  });
});

test('returns to direct chat without dropping its draft', async () => {
  listProviders.mockResolvedValue([]);
  useUIStore.setState({ settingsReturnPage: 'new-chat', newChatDraft: 'Keep this message' });
  render(<Settings />);

  expect(await screen.findByText('No providers configured yet.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Back to chat' }));
  expect(useUIStore.getState().activePage).toBe('new-chat');
  expect(useUIStore.getState().newChatDraft).toBe('Keep this message');
});

test('explains the desktop credential-store boundary in web development mode', async () => {
  listProviders.mockResolvedValue([]);
  render(<Settings />);

  expect(await screen.findByText(/web development client/i)).toBeInTheDocument();
  expect(screen.getByText(/API-key providers must be added from the Argus desktop app/i)).toBeInTheDocument();
});
