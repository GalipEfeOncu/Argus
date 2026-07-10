import React from 'react';
import { clsx } from 'clsx';
import './Badge.css';

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'neon' | 'outline';
}

export const Badge: React.FC<BadgeProps> = ({ className, variant = 'default', ...props }) => {
  return (
    <div className={clsx('argus-badge', `argus-badge--${variant}`, className)} {...props} />
  );
};
