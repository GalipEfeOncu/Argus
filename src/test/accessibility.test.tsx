import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import axe from 'axe-core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from '@/App';
import { useUIStore } from '@/stores/uiStore';

const { startBackend } = vi.hoisted(() => ({ startBackend: vi.fn() }));

vi.mock('@/hooks/useTauri', () => ({
  useTauri: () => ({
    status: 'stopped',
    isRunning: false,
    errorMsg: null,
    startBackend,
    stopBackend: vi.fn(),
    openDirectoryDialog: vi.fn(),
  }),
}));

describe('application accessibility smoke', () => {
  afterEach(cleanup);

  beforeEach(() => {
    startBackend.mockReset();
    useUIStore.setState({ activePage: 'dashboard' });
  });

  it('has no automatically detectable WCAG A/AA structural violations', async () => {
    const view = render(<App />);
    const result = await axe.run(view.container, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
      rules: { 'color-contrast': { enabled: false } },
    });
    expect(result.violations.map((violation) => `${violation.id}: ${violation.help}`)).toEqual([]);
  });

  it('exposes the stopped-sidecar recovery action to keyboard users', () => {
    const view = render(<App />);
    const retry = within(view.container).getByRole('button', { name: 'Backend stopped — click to start' });
    retry.focus();
    expect(retry).toHaveFocus();
    fireEvent.click(retry);
    expect(startBackend).toHaveBeenCalledTimes(1);
  });

  it('keeps the shell visible while the optional session workspace loads', async () => {
    useUIStore.setState({ activePage: 'session' });
    render(<App />);

    expect(within(screen.getByRole('main')).getByRole('status')).toHaveTextContent('Loading session workspace…');
    expect(screen.getByRole('button', { name: 'Dashboard' })).toBeInTheDocument();
    expect(await screen.findByText('No active session selected.', {}, { timeout: 5_000 })).toBeInTheDocument();
  });
});
