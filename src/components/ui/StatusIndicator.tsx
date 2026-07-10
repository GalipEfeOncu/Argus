import React from 'react';
import { clsx } from 'clsx';
import './StatusIndicator.css';

export interface StatusIndicatorProps extends React.HTMLAttributes<HTMLSpanElement> {
  status?: 'online' | 'offline' | 'busy' | 'idle';
}

export const StatusIndicator: React.FC<StatusIndicatorProps> = ({ 
  className, 
  status = 'online', 
  ...props 
}) => {
  return (
    <span 
      className={clsx('argus-status-indicator', `argus-status--${status}`, className)} 
      {...props} 
    />
  );
};
