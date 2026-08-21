import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { StatusBar } from '@/components/layout/StatusBar';

test('status bar reports only the canonical local runtime lifecycle', () => {
  render(<StatusBar backendStatus="running" />);

  expect(screen.getByText('Local runtime running')).toBeInTheDocument();
  expect(screen.queryByText(/authenticated|localhost|connected/i)).not.toBeInTheDocument();
});
