import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Dashboard } from '@/components/pages/Dashboard';
import { Sidebar } from '@/components/layout/Sidebar';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { SessionView } from '@/components/pages/SessionView';
import { useSessionStore } from '@/stores/sessionStore';
import { useUIStore } from '@/stores/uiStore';
import { useWorkspaceStore } from '@/stores/workspaceStore';
import type { ProjectSummary, SessionSummary } from '@/services/api';

const { listProjects, listSessions } = vi.hoisted(() => ({ listProjects: vi.fn(), listSessions: vi.fn() }));

vi.mock('@/services/api', () => ({ api: {
  projects: { list: () => listProjects() },
  sessions: { list: () => listSessions() },
} }));
vi.mock('@/components/chat/MessageList', () => ({ MessageList: () => <div>Timeline</div> }));
vi.mock('@/components/chat/MessageInput', () => ({ MessageInput: () => <div>Composer</div> }));
vi.mock('@/components/chat/ApprovalBar', () => ({ ApprovalBar: () => null }));
vi.mock('@/components/chat/SessionControls', () => ({ SessionControls: () => <div>Controls</div> }));

const project: ProjectSummary = {
  id: 'prj_argus', canonicalPath: '/work/argus', displayName: 'Argus', createdAtMs: 1, updatedAtMs: 1,
  gitMetadata: { isGit: true, rootPath: '/work/argus', head: 'abc', dirty: false, nestedRepositoryPaths: [], containsSymlinks: false, caseSensitive: true },
};
const session: SessionSummary = {
  id: 'ses_argus', name: 'Navigation polish', projectId: project.id, projectDisplayName: project.displayName,
  originalProjectPath: project.canonicalPath, goal: 'Connect durable workspace data', status: 'running',
  startedAtMs: Date.now(), updatedAtMs: Date.now(), completedAtMs: null,
};

beforeEach(() => {
  listProjects.mockReset();
  listSessions.mockReset();
  useUIStore.setState({ activePage: 'dashboard', sidebarCollapsed: false });
  useSessionStore.setState({ sessions: [], activeSessionId: null });
  useWorkspaceStore.setState({ projects: [], sessions: [], selectedProjectId: null, loading: false, loaded: true, error: null });
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
  expect(useWorkspaceStore.getState().selectedProjectId).toBe(project.id);
  expect(useUIStore.getState().activePage).toBe('dashboard');
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

test('sidebar exposes loading, empty, and retryable error states', () => {
  useWorkspaceStore.setState({ loading: true });
  render(<Sidebar />);
  expect(screen.getByRole('status')).toHaveTextContent('Loading local projects');

  act(() => useWorkspaceStore.setState({ loading: false, error: 'Local projects and sessions could not be loaded.' }));
  expect(screen.getByRole('alert')).toHaveTextContent('could not be loaded');
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();

  act(() => useWorkspaceStore.setState({ error: null, projects: [] }));
  expect(screen.getByText('No local projects registered.')).toBeInTheDocument();
});

test('dashboard exposes loading, empty, and retryable error states', () => {
  useWorkspaceStore.setState({ loading: true });
  const view = render(<Dashboard />);
  expect(screen.getByRole('status')).toHaveTextContent('Loading local sessions');

  act(() => useWorkspaceStore.setState({ loading: false, error: 'Local projects and sessions could not be loaded.' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Local workspace unavailable');
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();

  act(() => useWorkspaceStore.setState({ error: null, sessions: [] }));
  expect(screen.getByText('No sessions yet')).toBeInTheDocument();
  view.unmount();
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
});

test('a durable dashboard selection opens the real session and project breadcrumb', () => {
  useSessionStore.setState({ activeSessionId: session.id });
  useWorkspaceStore.setState({ projects: [project], sessions: [session] });
  render(<SessionView />);
  expect(screen.getByText('Argus')).toBeInTheDocument();
  expect(screen.getByText('Navigation polish')).toBeInTheDocument();
  expect(screen.getByText('Timeline')).toBeInTheDocument();
});
