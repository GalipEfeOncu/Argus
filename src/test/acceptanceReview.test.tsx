import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { AcceptanceReview } from '@/components/workflow/AcceptanceReview';

const { acceptance, acceptanceAction, acceptancePatch } = vi.hoisted(() => ({
  acceptance: vi.fn(), acceptanceAction: vi.fn(), acceptancePatch: vi.fn(),
}));

vi.mock('@/services/api', () => ({
  api: { sessions: { acceptance, acceptanceAction, acceptancePatch } },
}));

const review = {
  sessionId: 'session-1', workspaceMode: 'snapshot' as const, workspaceChecksum: 'a'.repeat(64), originalChecksum: 'b'.repeat(64), currentOriginalChecksum: 'b'.repeat(64),
  drifted: false, canApply: true, patchAvailable: true,
  files: [{ path: 'src/example.ts', change: 'modified' as const, additions: 2, deletions: 1, byteLength: 24 }],
  artifacts: [{ id: 'artifact-1', kind: 'diff', relativePath: 'src/example.ts', checksum: 'c'.repeat(64), metadata: {}, createdAtMs: 1 }],
  gates: [{ id: 'gate-1', role: 'tester', status: 'satisfied', evidenceCount: 1 }], unmetGates: [],
  limits: [{ counter: 'tokens', current: 4, threshold: 10, hard: false }],
  usage: { inputTokens: 2, outputTokens: 2, normalizedCost: 0.01, durationMs: 1000 }, coordinatorSummary: 'Tests and review are complete.', latestAction: null,
};

describe('AcceptanceReview', () => {
  it('shows bounded review evidence and requires retain for a patch export', async () => {
    acceptance.mockResolvedValue(review);
    render(<AcceptanceReview sessionId="session-1" status="completed" />);
    expect(await screen.findByText('Review isolated changes')).toBeInTheDocument();
    expect(screen.getByText('src/example.ts')).toBeInTheDocument();
    expect(screen.getByText(/Tokens: 4/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export patch' })).toBeEnabled();
    fireEvent.click(screen.getByLabelText('Clean up isolated workspace'));
    expect(screen.getByRole('button', { name: 'Export patch' })).toBeDisabled();
  });
});
