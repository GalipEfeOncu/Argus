import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Dashboard } from '@/components/pages/Dashboard';
import { Sidebar } from '@/components/layout/Sidebar';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { SessionView } from '@/components/pages/SessionView';
import { useSessionStore } from '@/stores/sessionStore';
import { useUIStore } from '@/stores/uiStore';
import { useWorkspaceStore } from '@/stores/workspaceStore';
import { useSessionRoomStore } from '@/stores/sessionRoomStore';
import { createSessionProjection } from '@/services/sessionProjection';
import { createConfiguration } from '@/services/sessionConfiguration';
import type { ProjectSummary, SessionSummary } from '@/services/api';

const { listProjects, listSessions, refreshProviderCredential } = vi.hoisted(() => ({
  listProjects: vi.fn(), listSessions: vi.fn(), refreshProviderCredential: vi.fn(),
}));

vi.mock('@/services/api', () => ({ api: {
  projects: { list: () => listProjects() },
  sessions: { list: () => listSessions() },
} }));
vi.mock('@/services/tauri', () => ({ tauriCommands: {
  refreshProviderCredential: (...args: unknown[]) => refreshProviderCredential(...args),
} }));
vi.mock('@/components/chat/MessageList', () => ({ MessageList: () => <div>Timeline</div> }));
vi.mock('@/components/chat/MessageInput', () => ({ MessageInput: () => <div>Composer</div> }));
vi.mock('@/components/chat/ApprovalBar', () => ({ ApprovalBar: () => null }));
vi.mock('@/components/chat/SessionControls', () => ({ SessionControls: () => <div>Controls</div> }));
vi.mock('@/components/workflow/RuntimeContext', () => ({ RuntimeContext: () => <div>Canonical runtime context</div> }));

const project: ProjectSummary = {
  id: 'prj_argus', canonicalPath: '/work/argus', displayName: 'Argus', createdAtMs: 1, updatedAtMs: 1,
  gitMetadata: { isGit: true, rootPath: '/work/argus', head: 'abc', dirty: false, nestedRepositoryPaths: [], containsSymlinks: false, caseSensitive: true },
};
const session: SessionSummary = {
  id: 'ses_argus', name: 'Navigation polish', projectId: project.id, projectDisplayName: project.displayName,
  sessionType: 'project',
  originalProjectPath: project.canonicalPath, goal: 'Connect durable workspace data', status: 'running',
  startedAtMs: Date.now(), updatedAtMs: Date.now(), completedAtMs: null,
};

beforeEach(() => {
  listProjects.mockReset();
  listSessions.mockReset();
  refreshProviderCredential.mockReset();
  refreshProviderCredential.mockResolvedValue(undefined);
  useUIStore.setState({ activePage: 'dashboard', sidebarCollapsed: false, agentPanelVisible: false });
  useSessionStore.setState({ sessions: [], activeSessionId: null });
  useWorkspaceStore.setState({ projects: [], sessions: [], selectedProjectId: null, loading: false, loaded: true, error: null });
  useSessionRoomStore.setState({ projections: {} });
});

afterEach(cleanup);

test('sidebar renders only durable projects and selects a real project', () => {
  useWorkspaceStore.setState({ projects: [project], sessions: [session] });
  render(<Sidebar />);

  expect(screen.getByRole('button', { name: 'Argus' })).toBeInTheDocument();
  expect(screen.queryByText('John Doe')).not.toBeInTheDocument();
  expect(screen.queryByText('PRO PLAN')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Search' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Argus' }));
  expect(screen.getByRole('button', { name: 'Argus' })).toHaveAttribute('aria-current', 'page');
  expect(useWorkspaceStore.getState().selectedProjectId).toBe(project.id);
  expect(useUIStore.getState().activePage).toBe('dashboard');
});

test('sidebar and dashboard navigation expose semantic current-page state to keyboard users', () => {
  useWorkspaceStore.setState({ projects: [project], sessions: [session] });
  render(<Sidebar />);
  const dashboard = screen.getByRole('button', { name: 'Dashboard' });
  expect(dashboard).toHaveAttribute('aria-current', 'page');
  fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
  expect(screen.getByRole('button', { name: 'Settings' })).toHaveAttribute('aria-current', 'page');
  const home = screen.getByRole('button', { name: 'Go to dashboard' });
  home.focus();
  fireEvent.click(home);
  expect(useUIStore.getState().activePage).toBe('dashboard');
});

test('primary New action opens direct chat', () => {
  render(<Sidebar />);
  fireEvent.click(screen.getByRole('button', { name: 'New chat' }));
  expect(useUIStore.getState().activePage).toBe('new-chat');
});

test('shell hydrates its catalog from the typed local API', async () => {
  listProjects.mockResolvedValue([project]);
  listSessions.mockResolvedValue([session]);
  useWorkspaceStore.setState({ loaded: false });
  render(<Dashboard />);

  expect(screen.getByRole('status')).toHaveTextContent('Loading local sessions');
  await waitFor(() => expect(screen.getByRole('button', { name: /^Navigation polish/ })).toBeInTheDocument());
  expect(listProjects).toHaveBeenCalledOnce();
  expect(listSessions).toHaveBeenCalledOnce();
  expect(useWorkspaceStore.getState().projects).toEqual([project]);
});

test('workspace refresh preserves successful project data when session loading fails', async () => {
  listProjects.mockResolvedValue([project]);
  listSessions.mockRejectedValue(new Error('private runtime detail'));
  useWorkspaceStore.setState({ loaded: false });
  render(<Dashboard />);

  expect(await screen.findByRole('alert')).toHaveTextContent('Local sessions could not be refreshed');
  expect(useWorkspaceStore.getState().projects).toEqual([project]);
  expect(screen.queryByText('private runtime detail')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Retry loading local projects and sessions' })).toBeInTheDocument();
});

test('sidebar exposes loading, empty, and retryable error states', () => {
  useWorkspaceStore.setState({ loading: true });
  render(<Sidebar />);
  expect(screen.getByRole('status')).toHaveTextContent('Loading local projects');

  act(() => useWorkspaceStore.setState({ loading: false, error: 'Local projects and sessions could not be loaded.' }));
  expect(screen.getByRole('alert')).toHaveTextContent('could not be loaded');
  expect(screen.getByRole('button', { name: 'Retry loading local projects' })).toBeInTheDocument();

  act(() => useWorkspaceStore.setState({ error: null, projects: [] }));
  expect(screen.getByText('No local projects registered.')).toBeInTheDocument();
});

test('dashboard error does not claim the local catalogue is empty', () => {
  useWorkspaceStore.setState({ loading: true });
  render(<Dashboard />);
  expect(screen.getByRole('status')).toHaveTextContent('Loading local sessions');

  act(() => useWorkspaceStore.setState({ loading: false, error: 'Local projects and sessions could not be loaded.' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Local projects and sessions could not be loaded');
  expect(screen.getByRole('button', { name: 'Retry loading local projects and sessions' })).toBeInTheDocument();
  expect(screen.queryByText('No sessions yet')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Start your first session' })).not.toBeInTheDocument();
});

test('dashboard empty state starts the described project-session setup', () => {
  render(<Dashboard />);
  expect(screen.getByText('No sessions yet')).toBeInTheDocument();
  expect(screen.getByText('Start a read-only session with Coordinator and one specialist at a time.')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Start your first session' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Start your first session' }));
  expect(useUIStore.getState().activePage).toBe('session-setup');
});

test('dashboard navigates semantically without exposing the unsupported retention action', () => {
  useWorkspaceStore.setState({ projects: [project], sessions: [session] });
  render(<Dashboard />);

  const open = screen.getByRole('button', { name: /^Navigation polish/ });
  open.focus();
  expect(open).toHaveFocus();
  fireEvent.click(open);
  expect(useSessionStore.getState().activeSessionId).toBe(session.id);
  expect(useUIStore.getState().activePage).toBe('session');
  expect(screen.queryByRole('button', { name: /Delete Navigation polish/ })).not.toBeInTheDocument();
});

test('shared-room breadcrumb uses the real project and has no no-op session menu', () => {
  render(<ChatPanel sessionId={session.id} sessionName={session.name} projectName={project.displayName} />);
  expect(screen.getByText('Argus')).toBeInTheDocument();
  expect(screen.getByText('Navigation polish')).toBeInTheDocument();
  expect(screen.queryByTitle('Session Options')).not.toBeInTheDocument();
  expect(screen.getByText('Navigation polish')).toHaveAttribute('aria-current', 'page');
  expect(screen.getByRole('navigation', { name: 'Session breadcrumb' })).toBeInTheDocument();
});

test('a durable dashboard selection opens the real session and project breadcrumb', () => {
  useSessionStore.setState({ activeSessionId: session.id });
  useWorkspaceStore.setState({ projects: [project], sessions: [session] });
  render(<SessionView />);
  expect(screen.getByText('Argus')).toBeInTheDocument();
  expect(screen.getByText('Navigation polish')).toBeInTheDocument();
  expect(screen.getByText('Timeline')).toBeInTheDocument();
});

test('restored direct chats renew their native provider lease', async () => {
  const modelRef = { providerId: 'provider-openrouter', modelId: 'free/chat-model:free', displayName: 'OpenRouter · Free chat model' };
  useSessionStore.getState().createSession({
    kind: 'chat', projectPath: '', task: 'Direct conversation', name: 'New chat',
    roleConfigs: [{ instanceId: 'coordinator', role: 'coordinator', enabled: true, modelRef }],
    configuration: createConfiguration({ coordinator: modelRef }),
  }, 'chat-session');
  render(<SessionView />);

  await waitFor(() => expect(refreshProviderCredential).toHaveBeenCalledWith('provider-openrouter'));
});

test('session context reports canonical status and restores toggle focus on close and Escape', async () => {
  useSessionStore.setState({ activeSessionId: session.id });
  useWorkspaceStore.setState({ projects: [project], sessions: [session] });
  useSessionRoomStore.setState({ projections: { [session.id]: { ...createSessionProjection(session.id), connection: 'connected', status: 'running' } } });
  render(<SessionView />);

  const toggle = screen.getByRole('button', { name: 'Open session context' });
  fireEvent.click(toggle);
  expect(await screen.findByRole('complementary', { name: 'Session context' })).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('connected · running');
  const close = screen.getByRole('button', { name: 'Close session context' });
  expect(close).toHaveFocus();
  fireEvent.click(close);
  await waitFor(() => expect(toggle).toHaveFocus());

  fireEvent.click(toggle);
  fireEvent.keyDown(document, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('complementary', { name: 'Session context' })).not.toBeInTheDocument());
  await waitFor(() => expect(toggle).toHaveFocus());
});
