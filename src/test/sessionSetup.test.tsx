import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SessionSetup } from '@/components/pages/SessionSetup';
import { useSettingsStore } from '@/stores/settingsStore';
import { useSessionStore } from '@/stores/sessionStore';
import { useUIStore } from '@/stores/uiStore';

const openDirectoryDialog = vi.fn();

vi.mock('@/hooks/useTauri', () => ({ useTauri: () => ({ openDirectoryDialog }) }));
vi.mock('@/services/eventSimulator', () => ({ eventSimulator: { start: vi.fn() } }));

afterEach(() => {
  cleanup();
  openDirectoryDialog.mockReset();
  useSettingsStore.setState({ defaultRoleModels: {} });
  useSessionStore.setState({ sessions: [], activeSessionId: null });
  useUIStore.setState({ activePage: 'dashboard' });
});

test('all seven setup sections are keyboard-focusable and a selected preset keeps resolved values visible', async () => {
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
