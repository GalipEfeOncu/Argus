import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSessionRoomStore } from '@/stores/sessionRoomStore';
import { createTimelineEntries, isTimelineEntrySpecialist } from '@/services/timelineModel';
import { TimelineRow } from './TimelineRow';
import { LiveTimelineAnnouncer } from './LiveTimelineAnnouncer';
import './MessageList.css';

interface MessageListProps {
  sessionId: string;
}

const ESTIMATED_ROW_HEIGHT = 92;
const OVERSCAN_ROWS = 6;

export const MessageList: React.FC<MessageListProps> = ({ sessionId }) => {
  const projection = useSessionRoomStore((state) => state.projections[sessionId]);
  const entries = useMemo(() => projection === undefined ? [] : createTimelineEntries(projection), [projection]);
  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(640);
  const [collapseSpecialists, setCollapseSpecialists] = useState(false);
  const [focusedEventId, setFocusedEventId] = useState<string | null>(null);
  const [rowHeights, setRowHeights] = useState<Record<string, number>>({});
  const [isFollowingLatest, setIsFollowingLatest] = useState(true);
  const [unreadCount, setUnreadCount] = useState(0);
  const previousEntryCount = useRef(0);

  const layout = useMemo(() => {
    const offsets: number[] = [];
    let totalHeight = 0;
    for (const entry of entries) {
      offsets.push(totalHeight);
      totalHeight += rowHeights[entry.id] ?? ESTIMATED_ROW_HEIGHT;
    }
    return { offsets, totalHeight };
  }, [entries, rowHeights]);

  const findIndexAtOffset = useCallback((offset: number) => {
    let low = 0;
    let high = layout.offsets.length;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      if (layout.offsets[middle] <= offset) low = middle + 1;
      else high = middle;
    }
    return Math.max(0, low - 1);
  }, [layout.offsets]);

  const measureRow = useCallback((eventId: string, height: number) => {
    if (height <= 0) return;
    setRowHeights((current) => current[eventId] === height ? current : { ...current, [eventId]: height });
  }, []);

  const visibleStart = Math.max(0, findIndexAtOffset(scrollTop) - OVERSCAN_ROWS);
  const visibleEnd = Math.min(entries.length, findIndexAtOffset(scrollTop + viewportHeight) + OVERSCAN_ROWS + 1);
  let start = visibleStart;
  let end = visibleEnd;
  const focusedIndex = focusedEventId === null ? -1 : entries.findIndex((entry) => entry.id === focusedEventId);
  if (focusedIndex >= 0 && (focusedIndex < start || focusedIndex >= end)) {
    start = Math.max(0, focusedIndex - OVERSCAN_ROWS);
    end = Math.min(entries.length, focusedIndex + OVERSCAN_ROWS + 1);
  }
  const visibleEntries = entries.slice(start, end);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) return;
    const updateSize = () => setViewportHeight(container.clientHeight || 640);
    updateSize();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(updateSize);
    observer?.observe(container);
    return () => observer?.disconnect();
  }, []);

  useEffect(() => {
    const added = entries.length - previousEntryCount.current;
    previousEntryCount.current = entries.length;
    if (added <= 0) return;
    if (!isFollowingLatest) {
      setUnreadCount((count) => count + added);
      return;
    }
    const targetScrollTop = Math.max(0, layout.totalHeight - viewportHeight);
    setScrollTop(targetScrollTop);
    const container = containerRef.current;
    if (container !== null && typeof container.scrollTo === 'function') container.scrollTo({ top: targetScrollTop, behavior: 'auto' });
  }, [entries.length, isFollowingLatest, layout.totalHeight, viewportHeight]);

  useEffect(() => {
    if (focusedEventId === null) return;
    document.getElementById(`event-${focusedEventId}`)?.focus();
  }, [focusedEventId, start, end]);

  const jumpToEvent = (eventId: string) => {
    const index = entries.findIndex((entry) => entry.id === eventId);
    if (index < 0) return;
    const targetScrollTop = Math.max(0, layout.offsets[index] - ESTIMATED_ROW_HEIGHT);
    setScrollTop(targetScrollTop);
    setFocusedEventId(eventId);
    const container = containerRef.current;
    if (container !== null && typeof container.scrollTo === 'function') {
      container.scrollTo({ top: targetScrollTop, behavior: 'auto' });
    }
  };

  const jumpToLatest = () => {
    const targetScrollTop = Math.max(0, layout.totalHeight - viewportHeight);
    setIsFollowingLatest(true);
    setUnreadCount(0);
    setScrollTop(targetScrollTop);
    const container = containerRef.current;
    if (container !== null && typeof container.scrollTo === 'function') container.scrollTo({ top: targetScrollTop, behavior: 'auto' });
  };

  if (entries.length === 0) {
    return (
      <div className="empty-state flex flex-col items-center justify-center h-full text-muted">
        <span className="text-4xl mb-3 opacity-50" aria-hidden="true">✦</span>
        <p>No room events yet. Send a task to Coordinator to get started.</p>
      </div>
    );
  }

  return (
    <section className="timeline-shell" aria-label="Shared room timeline">
      <div className="timeline-toolbar">
        <span>{entries.length.toLocaleString()} ordered events</span>
        <button type="button" aria-pressed={collapseSpecialists} onClick={() => setCollapseSpecialists((value) => !value)}>
          {collapseSpecialists ? 'Show specialist detail' : 'Collapse specialist detail'}
        </button>
      </div>
      <div
        className="timeline-viewport"
        ref={containerRef}
        role="log"
        aria-live="off"
        aria-label="Ordered shared-room events"
        onScroll={(event) => {
          const target = event.currentTarget;
          setScrollTop(target.scrollTop);
          const distanceFromLatest = target.scrollHeight - target.clientHeight - target.scrollTop;
          const followsLatest = distanceFromLatest <= ESTIMATED_ROW_HEIGHT;
          setIsFollowingLatest(followsLatest);
          if (followsLatest) setUnreadCount(0);
        }}
        onFocusCapture={(event) => {
          const row = (event.target as HTMLElement).closest<HTMLElement>('[data-event-id]');
          if (row !== null) setFocusedEventId(row.dataset.eventId ?? null);
        }}
      >
        <div style={{ height: layout.offsets[start] ?? 0 }} aria-hidden="true" />
        {visibleEntries.map((entry) => (
          <TimelineRow
            key={entry.id}
            entry={entry}
            collapsed={collapseSpecialists && isTimelineEntrySpecialist(entry)}
            onJumpToEvent={jumpToEvent}
            onMeasuredHeight={measureRow}
          />
        ))}
        <div style={{ height: Math.max(0, layout.totalHeight - (layout.offsets[end] ?? layout.totalHeight)) }} aria-hidden="true" />
      </div>
      {unreadCount > 0 && (
        <button className="timeline-unread" type="button" onClick={jumpToLatest}>
          {unreadCount} new event{unreadCount === 1 ? '' : 's'} · Jump to latest
        </button>
      )}
      <LiveTimelineAnnouncer latestEntry={entries.at(-1)} />
    </section>
  );
};
