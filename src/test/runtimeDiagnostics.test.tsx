import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RuntimeDiagnostics } from '@/components/workflow/RuntimeDiagnostics';

const { health, supportBundle } = vi.hoisted(() => ({ health: vi.fn(), supportBundle: vi.fn() }));

vi.mock('@/services/api', () => ({ api: { runtime: { health, supportBundle } } }));

describe('RuntimeDiagnostics', () => {
  it('turns a degraded local check into a visible recovery action without exposing sensitive data', async () => {
    health.mockResolvedValue({
      status: 'degraded', observedAtMs: 1,
      checks: [{ code: 'database_locked', status: 'degraded', summary: 'Local database is temporarily unavailable.', action: 'Wait and refresh.' }],
      queues: { runnableAssignments: 1, activeToolExecutions: 0, activeProviderOperations: 2, pendingApprovals: 0, pendingDecisions: 0, reservedLimits: 0 },
      writerLeases: { active: 1, expiredUnreleased: 0 }, providerLatency: [],
      eventLag: { newestEventAgeMs: 1000, sessionsWithEvents: 1, invalidPayloads: 0 }, usage: { inputTokens: 2, outputTokens: 3, normalizedCost: null, durationMs: 50, samples: 1 },
    });
    render(<RuntimeDiagnostics sessionId="session-1" />);
    expect(await screen.findByText('Action needed')).toBeInTheDocument();
    expect(screen.getByText('Wait and refresh.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export redacted support bundle' })).toBeInTheDocument();
    expect(screen.getByText(/never includes credentials, raw prompts/)).toBeInTheDocument();
  });
});
