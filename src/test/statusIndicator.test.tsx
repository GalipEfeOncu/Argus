import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { StatusIndicator } from '@/components/ui/StatusIndicator';
import { StatusBar } from '@/components/layout/StatusBar';

test('Testing Library renders an accessible status indicator', () => {
  render(<StatusIndicator aria-label="Backend connected" status="online" />);

  expect(screen.getByLabelText('Backend connected')).toHaveClass('argus-status--online');
});

test('status bar reports only the canonical local runtime lifecycle', () => {
  render(<StatusBar backendStatus="running" />);

  expect(screen.getByText('Local runtime running')).toBeInTheDocument();
  expect(screen.queryByText(/authenticated|localhost|connected/i)).not.toBeInTheDocument();
});
