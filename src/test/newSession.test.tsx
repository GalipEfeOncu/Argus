import { afterEach, beforeEach, expect, test } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { NewSession } from '@/components/pages/NewSession';
import { useUIStore } from '@/stores/uiStore';

beforeEach(() => {
  useUIStore.setState({ activePage: 'new-session' });
});

afterEach(cleanup);

test('presents a session-first choice without decorative card symbols', () => {
  render(<NewSession />);

  expect(screen.getByRole('heading', { name: 'Start a new session' })).toBeInTheDocument();
  expect(screen.getByText('START A NEW SESSION')).toBeInTheDocument();
  expect(screen.getByText('Choose a focused chat or configure a bounded project session.')).toBeInTheDocument();
  expect(screen.getByText('Open direct chat →')).toBeInTheDocument();
  expect(screen.getByText('Configure project session →')).toBeInTheDocument();
  expect(screen.queryByText('✦')).not.toBeInTheDocument();
  expect(screen.queryByText('⌘')).not.toBeInTheDocument();
});

test('routes each session choice to its real destination', () => {
  render(<NewSession />);

  fireEvent.click(screen.getByRole('button', { name: /New Chat/ }));
  expect(useUIStore.getState().activePage).toBe('new-chat');

  useUIStore.setState({ activePage: 'new-session' });
  fireEvent.click(screen.getByRole('button', { name: /New Project Session/ }));
  expect(useUIStore.getState().activePage).toBe('session-setup');
});
