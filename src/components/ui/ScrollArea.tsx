import React from 'react';
import * as ScrollAreaPrimitive from '@radix-ui/react-scroll-area';
import { clsx } from 'clsx';
import './ScrollArea.css';

export const ScrollArea = React.forwardRef<
  React.ElementRef<typeof ScrollAreaPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.Root>
>(({ className, children, ...props }, ref) => (
  <ScrollAreaPrimitive.Root
    ref={ref}
    className={clsx('argus-scroll-area', className)}
    {...props}
  >
    <ScrollAreaPrimitive.Viewport className="argus-scroll-viewport">
      {children}
    </ScrollAreaPrimitive.Viewport>
    <ScrollAreaPrimitive.Scrollbar
      className="argus-scroll-scrollbar"
      orientation="vertical"
    >
      <ScrollAreaPrimitive.Thumb className="argus-scroll-thumb" />
    </ScrollAreaPrimitive.Scrollbar>
    <ScrollAreaPrimitive.Scrollbar
      className="argus-scroll-scrollbar"
      orientation="horizontal"
    >
      <ScrollAreaPrimitive.Thumb className="argus-scroll-thumb" />
    </ScrollAreaPrimitive.Scrollbar>
    <ScrollAreaPrimitive.Corner className="argus-scroll-corner" />
  </ScrollAreaPrimitive.Root>
));
ScrollArea.displayName = ScrollAreaPrimitive.Root.displayName;
