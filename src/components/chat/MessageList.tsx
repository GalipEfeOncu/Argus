import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSessionRoomStore } from '@/stores/sessionRoomStore';
import { hasPendingAssistantResponse } from '@/services/sessionProjection';
import { createTimelineEntries, isTimelineEntrySpecialist } from '@/services/timelineModel';
import { TimelineRow } from './TimelineRow';
import { LiveTimelineAnnouncer } from './LiveTimelineAnnouncer';
import './MessageList.css';
import type { SessionKind } from '@/types/session';

interface MessageListProps {
  sessionId: string;
  sessionKind?: SessionKind;
}

const ESTIMATED_ROW_HEIGHT = 92;
const OVERSCAN_ROWS = 6;

export const MessageList: React.FC<MessageListProps> = ({ sessionId, sessionKind = 'project' }) => {
  const projection = useSessionRoomStore((state) => state.projections[sessionId]);
  const entries = useMemo(() => {
    if (projection === undefined) return [];
    const next = createTimelineEntries(projection);
    // Direct chat keeps the ordered event log in the projection, but presents
    // only conversational messages and actionable errors. Deltas and usage
    // events update the message projection and should not become chat cards.
    return sessionKind === 'chat'
      ? next.filter((entry) => entry.event.type === 'message.created' || entry.event.type === 'error.created')
      : next;
  }, [projection, sessionKind]);
  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(640);
  const [collapseSpecialists, setCollapseSpecialists] = useState(false);
  const [focusedEventId, setFocusedEventId] = useState<string | null>(null);
  const [rowHeights, setRowHeights] = useState<Record<string, number>>({});
  const [isFollowingLatest, setIsFollowingLatest] = useState(true);
  const [unreadCount, setUnreadCount] = useState(0);
  const previousEntryCount = useRef<number | null>(null);
  const previousHumanEntryId = useRef<string | null>(null);
  const promptAnchor = useRef<{ id: string; offset: number } | null>(null);

  const layout = useMemo(() => {
    const offsets: number[] = [];
    let totalHeight = 0;
    for (const entry of entries) {
      offsets.push(totalHeight);
      totalHeight += rowHeights[entry.id] ?? ESTIMATED_ROW_HEIGHT;
    }
    return { offsets, totalHeight };
  }, [entries, rowHeights]);

  let latestHumanIndex = -1;
  if (sessionKind === 'chat') {
    entries.forEach((entry, index) => {
      if (entry.event.type === 'message.created' && entry.event.payload.authorKind === 'human') {
        latestHumanIndex = index;
      }
    });
  }
  const latestHumanEntryId = latestHumanIndex >= 0 ? entries[latestHumanIndex]?.id ?? null : null;
  const latestHumanOffset = latestHumanIndex >= 0 ? layout.offsets[latestHumanIndex] ?? 0 : null;
  const trailingScrollSpace = sessionKind === 'chat' ? viewportHeight : 0;
  const latestScrollTop = Math.max(0, layout.totalHeight + trailingScrollSpace - viewportHeight);

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

  const moveViewport = useCallback((targetScrollTop: number) => {
    const nextScrollTop = Math.max(0, targetScrollTop);
    setScrollTop(nextScrollTop);
    const container = containerRef.current;
    if (container !== null && typeof container.scrollTo === 'function') {
      container.scrollTo({ top: nextScrollTop, behavior: 'auto' });
    }
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
  const waitingForAssistant = sessionKind === 'chat' && projection !== undefined && hasPendingAssistantResponse(projection);

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
    const previousCount = previousEntryCount.current;
    const previousHumanId = previousHumanEntryId.current;
    const added = entries.length - (previousCount ?? 0);
    previousEntryCount.current = entries.length;
    previousHumanEntryId.current = latestHumanEntryId;
    if (added <= 0) return;

    if (
      sessionKind === 'chat'
      && previousCount !== null
      && latestHumanEntryId !== null
      && latestHumanEntryId !== previousHumanId
    ) {
      const targetScrollTop = latestHumanOffset ?? 0;
      promptAnchor.current = { id: latestHumanEntryId, offset: targetScrollTop };
      setUnreadCount(0);
      moveViewport(targetScrollTop);
      return;
    }

    if (sessionKind === 'chat' && promptAnchor.current !== null) return;

    if (!isFollowingLatest) {
      if (promptAnchor.current === null) setUnreadCount((count) => count + added);
      return;
    }
    promptAnchor.current = null;
    moveViewport(latestScrollTop);
  }, [entries.length, isFollowingLatest, latestHumanEntryId, latestHumanOffset, latestScrollTop, moveViewport, sessionKind]);

  useEffect(() => {
    if (sessionKind !== 'chat' || latestHumanEntryId === null || latestHumanOffset === null) return;
    const anchor = promptAnchor.current;
    if (anchor === null || anchor.id !== latestHumanEntryId || anchor.offset === latestHumanOffset) return;
    anchor.offset = latestHumanOffset;
    moveViewport(latestHumanOffset);
  }, [latestHumanEntryId, latestHumanOffset, moveViewport, sessionKind]);

  useEffect(() => {
    if (focusedEventId === null) return;
    document.getElementById(`event-${focusedEventId}`)?.focus();
  }, [focusedEventId, start, end]);

  const jumpToEvent = (eventId: string) => {
    const index = entries.findIndex((entry) => entry.id === eventId);
    if (index < 0) return;
    const targetScrollTop = Math.max(0, layout.offsets[index] - ESTIMATED_ROW_HEIGHT);
    promptAnchor.current = null;
    moveViewport(targetScrollTop);
    setFocusedEventId(eventId);
  };

  const jumpToLatest = () => {
    promptAnchor.current = null;
    setIsFollowingLatest(true);
    setUnreadCount(0);
    moveViewport(latestScrollTop);
  };

  if (entries.length === 0) {
    return (
      <div className="empty-state flex flex-col items-center justify-center h-full text-muted">
        <span className="text-4xl mb-3 opacity-50" aria-hidden="true">✦</span>
        <p>{sessionKind === 'chat' ? 'No messages yet. Write something below to start the conversation.' : 'No room events yet. Send a task to Coordinator to get started.'}</p>
      </div>
    );
  }

  return (
    <section className={`timeline-shell${sessionKind === 'chat' ? ' timeline-shell--chat' : ''}`} aria-label={sessionKind === 'chat' ? 'Conversation timeline' : 'Shared room timeline'}>
      {sessionKind !== 'chat' && <div className="timeline-toolbar">
        <span>{entries.length.toLocaleString()} ordered events</span>
        <button type="button" aria-pressed={collapseSpecialists} onClick={() => setCollapseSpecialists((value) => !value)}>
          {collapseSpecialists ? 'Show specialist detail' : 'Collapse specialist detail'}
        </button>
      </div>}
      <div
        className="timeline-viewport"
        ref={containerRef}
        role="log"
        aria-live="off"
        aria-label={sessionKind === 'chat' ? 'Ordered conversation events' : 'Ordered shared-room events'}
        onScroll={(event) => {
          const target = event.currentTarget;
          setScrollTop(target.scrollTop);
          const anchor = promptAnchor.current;
          if (anchor !== null && Math.abs(target.scrollTop - anchor.offset) > 1) promptAnchor.current = null;
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
        <div className="timeline-content-column">
          <div style={{ height: layout.offsets[start] ?? 0 }} aria-hidden="true" />
          {visibleEntries.map((entry) => (
            <TimelineRow
              key={entry.id}
              entry={entry}
              collapsed={collapseSpecialists && isTimelineEntrySpecialist(entry)}
              onJumpToEvent={jumpToEvent}
              onMeasuredHeight={measureRow}
              presentation={sessionKind === 'chat' ? 'chat' : 'room'}
              messageStreaming={entry.event.type === 'message.created' && projection?.messages[entry.event.payload.messageId]?.streaming === true}
            />
          ))}
          {waitingForAssistant && end === entries.length && <div className="chat-typing-indicator" role="status" aria-label="Argus is thinking">
            <span className="chat-typing-indicator__dot" />
            <span>Argus is thinking</span>
          </div>}
          <div style={{ height: Math.max(0, layout.totalHeight - (layout.offsets[end] ?? layout.totalHeight)) + trailingScrollSpace }} aria-hidden="true" />
        </div>
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
