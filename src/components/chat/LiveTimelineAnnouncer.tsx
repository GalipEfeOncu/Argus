import React, { useEffect, useRef, useState } from 'react';
import type { TimelineEntry } from '@/services/timelineModel';

interface LiveTimelineAnnouncerProps {
  latestEntry: TimelineEntry | undefined;
}

const THROTTLE_MS = 900;

/** Keeps screen-reader updates informative without narrating each streamed token. */
export const LiveTimelineAnnouncer: React.FC<LiveTimelineAnnouncerProps> = ({ latestEntry }) => {
  const [announcement, setAnnouncement] = useState('');
  const announcedId = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef<TimelineEntry | null>(null);

  useEffect(() => {
    if (latestEntry === undefined || latestEntry.id === announcedId.current) return;
    pending.current = latestEntry;
    const announce = () => {
      const next = pending.current;
      if (next === null) return;
      announcedId.current = next.id;
      setAnnouncement(`${next.title}: ${next.summary}`);
      pending.current = null;
      timer.current = null;
    };
    if (timer.current !== null) return;
    timer.current = setTimeout(announce, THROTTLE_MS);
  }, [latestEntry]);

  useEffect(() => () => {
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = null;
  }, []);

  return <div className="sr-only" aria-live="polite" aria-atomic="true">{announcement}</div>;
};
