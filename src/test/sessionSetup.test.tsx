import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SessionSetup } from '@/components/pages/SessionSetup';
import { useSettingsStore } from '@/stores/settingsStore';
import { useSessionStore } from '@/stores/sessionStore';
import { useUIStore } from '@/stores/uiStore';

const openDirectoryDialog = vi.fn();
const createSessionRequest = vi.fn();
const listAgentDefinitions = vi.fn();
const refreshProviderCredential = vi.fn();
const listProviders = vi.fn();
const listProviderModels = vi.fn();
const configuredModel = { providerId: 'prv_configured', modelId: 'model-1', displayName: 'Configured model' };
const configuredModels = Object.fromEntries(['coordinator', 'planner', 'builder', 'reviewer', 'tester', 'ui_agent'].map((role) => [role, configuredModel]));

vi.mock('@/hooks/useTauri', () => ({ useTauri: () => ({ openDirectoryDialog }) }));
vi.mock('@/services/tauri', () => ({ tauriCommands: { refreshProviderCredential: (...args: unknown[]) => refreshProviderCredential(...args) } }));
vi.mock('@/services/api', () => ({ api: {
  sessions: { create: (...args: unknown[]) => createSessionRequest(...args) },
  agentDefinitions: { list: () => listAgentDefinitions() },
  providers: {
    list: () => listProviders(),
    listModels: () => listProviderModels(),
  },
} }));

beforeEach(() => {
  openDirectoryDialog.mockReset();
  createSessionRequest.mockReset();
  listAgentDefinitions.mockReset();
  refreshProviderCredential.mockReset();
  listProviders.mockReset();
  listProviderModels.mockReset();
  refreshProviderCredential.mockResolvedValue(undefined);
  createSessionRequest.mockResolvedValue({ id: 'ses_live', agentSnapshots: [] });
  listAgentDefinitions.mockResolvedValue([]);
  listProviders.mockResolvedValue([{ id: 'prv_configured', displayName: 'Configured provider', credentialConfigured: false }]);
  listProviderModels.mockResolvedValue({ models: [{ id: 'model-1', displayName: 'Configured model', supportsStructuredOutput: true }] });
  useSettingsStore.setState({ defaultRoleModels: configuredModels });
  useSessionStore.setState({ sessions: [], activeSessionId: null });
  useUIStore.setState({ activePage: 'dashboard' });
});

afterEach(() => {
  cleanup();
});

test('a providerless setup remains disabled and explains every missing selected model', async () => {
  useSettingsStore.setState({ defaultRoleModels: {} });
  openDirectoryDialog.mockResolvedValue('/project');
  render(<SessionSetup />);
  fireEvent.click(screen.getByRole('button', { name: 'Browse' }));
  await waitFor(() => expect(screen.getByDisplayValue('/project')).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Goal'), { target: { value: 'Inspect the project' } });
  expect(screen.getByRole('button', { name: 'Start read-only Coordinator session' })).toBeDisabled();
  expect(screen.getByRole('alert')).toHaveTextContent('Coordinator requires a configured model.');
  expect(screen.getByRole('alert')).toHaveTextContent('A configured read-only specialist model is required.');
  expect(createSessionRequest).not.toHaveBeenCalled();
});

test('provider catalogue failures disable start and expose a retry without leaking raw errors', async () => {
  listProviders.mockRejectedValueOnce(new Error('secret provider response body'));
  render(<SessionSetup />);

  const alertText = await screen.findByText(/Configured provider models could not be loaded/);
  expect(alertText.closest('[role="alert"]')).not.toBeNull();
  expect(screen.queryByText('secret provider response body')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Start read-only Coordinator session' })).toBeDisabled();

  fireEvent.click(screen.getByRole('button', { name: 'Retry provider models' }));
  await waitFor(() => expect(listProviders).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Retry provider models' })).not.toBeInTheDocument());
});

test('the truthful read-only setup is keyboard-focusable and creates a narrowed live session', async () => {
  openDirectoryDialog.mockResolvedValue('/project');
  render(<SessionSetup />);
  expect(screen.getByRole('heading', { name: /1 — Inspection goal and workspace/i })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /5 — Review/i })).toBeInTheDocument();
  expect(screen.getByRole('note')).toHaveTextContent('at most one specialist per turn');
  expect(screen.queryByRole('button', { name: 'Quick' })).not.toBeInTheDocument();
  expect(screen.queryByLabelText('direct write')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Permission profile')).not.toBeInTheDocument();
  expect(screen.queryByText(/Required role gates/i)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Browse' }));
  await waitFor(() => expect(screen.getByDisplayValue('/project')).toBeInTheDocument());
  const goal = screen.getByLabelText('Goal');
  goal.focus();
  expect(document.activeElement).toBe(goal);
  fireEvent.change(goal, { target: { value: 'Verify keyboard access' } });
  const start = screen.getByRole('button', { name: 'Start read-only Coordinator session' });
  start.focus();
  expect(document.activeElement).toBe(start);
  expect(start).toBeEnabled();
  fireEvent.click(start);
  await waitFor(() => expect(createSessionRequest).toHaveBeenCalledOnce());
  expect(createSessionRequest).toHaveBeenCalledWith(expect.objectContaining({
    projectPath: '/project', goal: 'Verify keyboard access', workspaceMode: 'worktree', acknowledgeDirectWrite: false,
    configuration: expect.objectContaining({
      availableAgentIds: ['builtin-planner'], requiredRoleRules: [], acknowledgements: [],
      executionLimits: expect.objectContaining({ maxParallelReadOnlyAssignments: 1, maxRevisionsPerFinding: 0 }),
      approvalPolicy: expect.objectContaining({ permissionProfile: 'balanced', behavior: 'ask_by_policy', preauthorizedCapabilities: [], capabilityOverrides: {}, limitResolution: 'stop' }),
      workspacePolicy: { mode: 'worktree' },
    }),
  }));
  const request = createSessionRequest.mock.calls[0]?.[0] as {
    agents: Array<{ id: string; capabilities?: string[]; permissionProfile: string; skillIds?: string[]; toolAllowlist?: string[] }>;
  };
  expect(request.agents).toEqual(expect.arrayContaining([
    expect.objectContaining({ id: 'coordinator', permissionProfile: 'balanced', skillIds: [] }),
  ]));
  expect(request.agents.every((agent) => ['strict', 'balanced'].includes(agent.permissionProfile))).toBe(true);
  expect(request.agents.every((agent) => (agent.skillIds ?? []).length === 0)).toBe(true);
  expect(request.agents.every((agent) => (agent.toolAllowlist ?? []).every((tool) => ['read_file', 'list_dir', 'search_files'].includes(tool)))).toBe(true);
  expect(request.agents.filter((agent) => agent.id !== 'coordinator').every((agent) => (agent.capabilities ?? []).every((capability) => capability === 'workspace.read'))).toBe(true);
  await waitFor(() => expect(useSessionStore.getState().sessions[0]?.id).toBe('ses_live'));
  expect(useSessionStore.getState().sessions[0]?.configuration.preset).toBe('custom');
  expect(useSessionStore.getState().sessions[0]?.configuration.availableAgentIds).toEqual(['builtin-planner']);
});

test('unsupported mutation and preauthorization controls are not exposed or submitted', () => {
  render(<SessionSetup />);
  expect(screen.queryByText(/Direct write has limited rollback/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/No-interruption mode/i)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/Pre-author/i)).not.toBeInTheDocument();
  expect(screen.getByText(/Workspace writes, shell commands, test execution/)).toBeInTheDocument();
});

test('a selected Coordinator override keeps its stricter permission profile', async () => {
  listAgentDefinitions.mockResolvedValueOnce([{
    id: 'team.coordinator.v2', name: 'Focused Coordinator', kind: 'builtin_override',
    role: 'coordinator', baseRole: 'coordinator', templateVersion: '2.0.0',
    systemPrompt: 'Route narrowly.', modelBinding: { providerProfileId: 'local', modelId: 'model' },
    capabilities: ['coordination.route'], skillIds: [], toolAllowlist: [], evidenceKinds: ['coordination_summary'],
    permissionProfile: 'strict', outputLanguage: 'en', createdAtMs: 1,
  }]);
  openDirectoryDialog.mockResolvedValue('/project');
  render(<SessionSetup />);
  await waitFor(() => expect(screen.getByRole('option', { name: 'Focused Coordinator' })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Definition version'), { target: { value: 'team.coordinator.v2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Browse' }));
  await waitFor(() => expect(screen.getByDisplayValue('/project')).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Goal'), { target: { value: 'Use the selected Coordinator' } });
  fireEvent.click(screen.getByRole('button', { name: 'Start read-only Coordinator session' }));

  await waitFor(() => expect(createSessionRequest).toHaveBeenCalledOnce());
  expect(createSessionRequest).toHaveBeenCalledWith(expect.objectContaining({
    agents: expect.arrayContaining([expect.objectContaining({
      id: 'coordinator', agentDefinitionId: 'team.coordinator.v2', permissionProfile: 'strict',
    })]),
  }));
});

test('a failed live session creation keeps the simulator inactive and explains the recovery step', async () => {
  createSessionRequest.mockRejectedValueOnce(new Error('backend unavailable'));
  openDirectoryDialog.mockResolvedValue('/project');
  render(<SessionSetup />);
  fireEvent.click(screen.getByRole('button', { name: 'Browse' }));
  await waitFor(() => expect(screen.getByDisplayValue('/project')).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Goal'), { target: { value: 'Create a live session' } });
  fireEvent.click(screen.getByRole('button', { name: 'Start read-only Coordinator session' }));

  expect(await screen.findByRole('alert')).toHaveTextContent('could not create this isolated session');
  expect(useSessionStore.getState().sessions).toEqual([]);
});
