import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import axe from 'axe-core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Profile, profileInitials } from '@/components/pages/Profile';
import { Sidebar } from '@/components/layout/Sidebar';
import { useLocalProfileStore } from '@/stores/localProfileStore';
import { useUIStore } from '@/stores/uiStore';

const { getProfile, patchProfile } = vi.hoisted(() => ({
  getProfile: vi.fn(),
  patchProfile: vi.fn(),
}));

vi.mock('@/services/api', async (loadOriginal) => {
  const original = await loadOriginal<typeof import('@/services/api')>();
  return { ...original, api: { ...original.api, profile: { get: getProfile, patch: patchProfile } } };
});

vi.mock('@/hooks/useWorkspaceCatalog', () => ({ useWorkspaceCatalog: () => ({ refresh: vi.fn() }) }));

describe('offline local profile', () => {
  afterEach(cleanup);

  beforeEach(() => {
    getProfile.mockReset();
    patchProfile.mockReset();
    useLocalProfileStore.setState({ profile: null, status: 'unconfigured', error: null });
    useUIStore.setState({ activePage: 'dashboard', sidebarCollapsed: false });
  });

  it('creates a profile and renders initials from the backend-confirmed response', async () => {
    patchProfile.mockResolvedValue({ displayName: 'Ada Lovelace', bio: 'Local builder', createdAtMs: 1, updatedAtMs: 1 });
    render(<Profile />);

    fireEvent.click(screen.getByRole('button', { name: 'Create local profile' }));
    fireEvent.change(screen.getByLabelText('Display name'), { target: { value: ' Ada Lovelace ' } });
    fireEvent.change(screen.getByLabelText(/Bio/), { target: { value: ' Local builder ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create profile' }));

    await waitFor(() => expect(patchProfile).toHaveBeenCalledWith({ displayName: 'Ada Lovelace', bio: 'Local builder' }));
    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByText('AL')).toBeInTheDocument();
  });

  it('keeps the draft after a save failure and exposes the error accessibly', async () => {
    useLocalProfileStore.setState({
      profile: { displayName: 'Ada', bio: null, createdAtMs: 1, updatedAtMs: 1 },
      status: 'ready',
      error: null,
    });
    patchProfile.mockRejectedValue(new Error('offline'));
    render(<Profile />);

    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    fireEvent.change(screen.getByLabelText('Display name'), { target: { value: 'Grace Hopper' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Your draft is still here');
    expect(screen.getByLabelText('Display name')).toHaveValue('Grace Hopper');
    expect(useLocalProfileStore.getState().profile?.displayName).toBe('Ada');
  });

  it('uses a keyboard-accessible sidebar profile button without placeholder identity or plan copy', () => {
    const view = render(<Sidebar />);
    const button = screen.getByRole('button', { name: 'Set up local profile' });

    expect(view.queryByText('John Doe')).not.toBeInTheDocument();
    expect(view.queryByText('PRO PLAN')).not.toBeInTheDocument();
    button.focus();
    expect(button).toHaveFocus();
    fireEvent.click(button);
    expect(useUIStore.getState().activePage).toBe('profile');
  });

  it('has an accessible unconfigured form', async () => {
    const view = render(<Profile />);
    fireEvent.click(screen.getByRole('button', { name: 'Create local profile' }));
    const result = await axe.run(view.container, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
      rules: { 'color-contrast': { enabled: false } },
    });
    expect(result.violations.map((violation) => violation.id)).toEqual([]);
  });

  it('derives at most two Unicode initials', () => {
    expect(profileInitials('İpek Öz')).toBe('İÖ');
  });
});
