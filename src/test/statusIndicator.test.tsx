import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { StatusIndicator } from '@/components/ui/StatusIndicator';

test('Testing Library renders an accessible status indicator', () => {
  render(<StatusIndicator aria-label="Backend connected" status="online" />);

  expect(screen.getByLabelText('Backend connected')).toHaveClass('argus-status--online');
});
