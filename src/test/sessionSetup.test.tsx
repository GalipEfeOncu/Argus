import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SessionSetup } from '@/components/pages/SessionSetup';
import { useSettingsStore } from '@/stores/settingsStore';
import { useSessionStore } from '@/stores/sessionStore';
import { useUIStore } from '@/stores/uiStore';

const openDirectoryDialog = vi.fn();
const createSessionRequest = vi.fn();
const listAgentDefinitions = vi.fn();
const listSkills = vi.fn();
const setSkillEnabled = vi.fn();

vi.mock('@/hooks/useTauri', () => ({ useTauri: () => ({ openDirectoryDialog }) }));
vi.mock('@/services/api', () => ({ api: {
  sessions: { create: (...args: unknown[]) => createSessionRequest(...args) },
  agentDefinitions: { list: () => listAgentDefinitions() },
  skills: { list: () => listSkills(), setEnabled: (...args: unknown[]) => setSkillEnabled(...args) },
} }));

beforeEach(() => {
  openDirectoryDialog.mockReset();
  createSessionRequest.mockReset();
  listAgentDefinitions.mockReset();
  listSkills.mockReset();
  setSkillEnabled.mockReset();
  createSessionRequest.mockResolvedValue({ id: 'ses_live', agentSnapshots: [] });
  listAgentDefinitions.mockResolvedValue([]);
  listSkills.mockResolvedValue([]);
  useSettingsStore.setState({ defaultRoleModels: {} });
  useSessionStore.setState({ sessions: [], activeSessionId: null });
  useUIStore.setState({ activePage: 'dashboard' });
});

afterEach(() => {
  cleanup();
});

test('all seven setup sections are keyboard-focusable and a selected preset creates a live isolated session', async () => {
  openDirectoryDialog.mockResolvedValue('/project');
  render(<SessionSetup />);
  expect(screen.getByRole('heading', { name: /1 — Goal and workspace/i })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /7 — Review/i })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Quick' }));
  expect(screen.getByDisplayValue('0')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Browse' }));
  await waitFor(() => expect(screen.getByDisplayValue('/project')).toBeInTheDocument());
  const goal = screen.getByLabelText('Goal');
  goal.focus();
  expect(document.activeElement).toBe(goal);
  fireEvent.change(goal, { target: { value: 'Verify keyboard access' } });
  const start = screen.getByRole('button', { name: 'Start Coordinator session' });
  start.focus();
  expect(document.activeElement).toBe(start);
  expect(start).toBeEnabled();
  fireEvent.click(start);
  await waitFor(() => expect(createSessionRequest).toHaveBeenCalledOnce());
  expect(createSessionRequest).toHaveBeenCalledWith(expect.objectContaining({
    projectPath: '/project', goal: 'Verify keyboard access', workspaceMode: 'worktree',
  }));
  await waitFor(() => expect(useSessionStore.getState().sessions[0]?.id).toBe('ses_live'));
  expect(useSessionStore.getState().sessions[0]?.configuration.preset).toBe('quick');
  expect(useSessionStore.getState().sessions[0]?.configuration.availableAgentIds).toEqual(['builtin-builder']);
});

test('direct write and Autonomous no-interruption require their visible acknowledgements', async () => {
  openDirectoryDialog.mockResolvedValue('/project');
  render(<SessionSetup />);
  fireEvent.click(screen.getByRole('button', { name: 'Browse' }));
  await waitFor(() => expect(screen.getByDisplayValue('/project')).toBeInTheDocument());
  fireEvent.click(screen.getByLabelText('direct write'));
  expect(screen.getByText('Direct write has limited rollback.')).toBeInTheDocument();
  expect(screen.getByLabelText('I understand that rollback is limited.')).not.toBeChecked();
  fireEvent.change(screen.getByLabelText('Permission profile'), { target: { value: 'autonomous' } });
  fireEvent.click(screen.getByLabelText('No-interruption mode (pre-authorize session)'));
  expect(screen.getByText('/project', { selector: 'strong' })).toBeInTheDocument();
  expect(screen.getByLabelText('I explicitly acknowledge these capabilities for this workspace.')).not.toBeChecked();
  fireEvent.click(screen.getByLabelText('I explicitly acknowledge these capabilities for this workspace.'));
  fireEvent.click(screen.getByLabelText('workspace.read'));
  expect(screen.getByLabelText('I explicitly acknowledge these capabilities for this workspace.')).not.toBeChecked();
  fireEvent.click(screen.getByLabelText('I explicitly acknowledge these capabilities for this workspace.'));
  openDirectoryDialog.mockResolvedValueOnce('/next-project');
  fireEvent.click(screen.getByRole('button', { name: 'Browse' }));
  await waitFor(() => expect(screen.getByDisplayValue('/next-project')).toBeInTheDocument());
  expect(screen.getByLabelText('I explicitly acknowledge these capabilities for this workspace.')).not.toBeChecked();
});

test('a selected Coordinator override is sent with its immutable definition and permission profile', async () => {
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
  fireEvent.click(screen.getByRole('button', { name: 'Start Coordinator session' }));

  await waitFor(() => expect(createSessionRequest).toHaveBeenCalledOnce());
  expect(createSessionRequest).toHaveBeenCalledWith(expect.objectContaining({
    agents: expect.arrayContaining([expect.objectContaining({
      id: 'coordinator', agentDefinitionId: 'team.coordinator.v2', permissionProfile: 'strict',
    })]),
  }));
});

test('local skills show a trust review, stay unassigned while disabled, and snapshot only after explicit enablement', async () => {
  const skill = {
    id: 'skl_review', manifest: { name: 'Accessibility review', version: '1.0.0' }, enabled: false,
    trustState: 'review_required', requestedTools: [], requestedPermissions: [],
  };
  listSkills.mockResolvedValueOnce([skill]);
  setSkillEnabled.mockResolvedValueOnce({ ...skill, enabled: true, trustState: 'enabled' });
  openDirectoryDialog.mockResolvedValue('/project');
  render(<SessionSetup />);
  expect(await screen.findByText('Accessibility review 1.0.0')).toBeInTheDocument();
  expect(screen.getByLabelText('Use for this Coordinator session')).toBeDisabled();
  fireEvent.click(screen.getByLabelText('Enable after review'));
  await waitFor(() => expect(setSkillEnabled).toHaveBeenCalledWith('skl_review', true));
  await waitFor(() => expect(screen.getByLabelText('Use for this Coordinator session')).toBeEnabled());
  fireEvent.click(screen.getByLabelText('Use for this Coordinator session'));
  fireEvent.click(screen.getByRole('button', { name: 'Browse' }));
  await waitFor(() => expect(screen.getByDisplayValue('/project')).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Goal'), { target: { value: 'Review safely' } });
  fireEvent.click(screen.getByRole('button', { name: 'Start Coordinator session' }));

  await waitFor(() => expect(createSessionRequest).toHaveBeenCalledWith(expect.objectContaining({
    agents: expect.arrayContaining([expect.objectContaining({ id: 'coordinator', skillIds: ['skl_review'] })]),
  })));
});

test('a failed live session creation keeps the simulator inactive and explains the recovery step', async () => {
  createSessionRequest.mockRejectedValueOnce(new Error('backend unavailable'));
  openDirectoryDialog.mockResolvedValue('/project');
  render(<SessionSetup />);
  fireEvent.click(screen.getByRole('button', { name: 'Browse' }));
  await waitFor(() => expect(screen.getByDisplayValue('/project')).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Goal'), { target: { value: 'Create a live session' } });
  fireEvent.click(screen.getByRole('button', { name: 'Start Coordinator session' }));

  expect(await screen.findByRole('alert')).toHaveTextContent('could not create this isolated session');
  expect(useSessionStore.getState().sessions).toEqual([]);
});
