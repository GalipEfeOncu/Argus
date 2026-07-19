import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { TimelineEntry } from '@/services/timelineModel';
import './TimelineRow.css';

interface TimelineRowProps {
  entry: TimelineEntry;
  collapsed: boolean;
  onJumpToEvent: (eventId: string) => void;
  onMeasuredHeight: (eventId: string, height: number) => void;
}

const kindLabels: Record<TimelineEntry['kind'], string> = {
  human: 'Human', coordinator: 'Coordinator', specialist: 'Specialist', system: 'System', tool: 'Tool', assignment: 'Assignment', handoff: 'Handoff', evidence: 'Evidence', gate: 'Gate', limit: 'Limit', decision: 'Decision', usage: 'Usage', diff: 'Diff', error: 'Error',
};

export const TimelineRow: React.FC<TimelineRowProps> = ({ entry, collapsed, onJumpToEvent, onMeasuredHeight }) => {
  const [open, setOpen] = useState(!collapsed);
  const [enhancedDiff, setEnhancedDiff] = useState<string | null>(null);
  const rowRef = useRef<HTMLElement>(null);
  const isCollapsed = collapsed && !open;
  const event = entry.event;

  useEffect(() => {
    if (collapsed) setOpen(false);
  }, [collapsed]);

  useLayoutEffect(() => {
    const row = rowRef.current;
    if (row === null) return;
    const measure = () => onMeasuredHeight(entry.id, row.getBoundingClientRect().height);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(row);
    return () => observer.disconnect();
  }, [entry.id, onMeasuredHeight]);

  const loadDiffEnhancement = async () => {
    const { highlightDiffMetadata } = await import('@/services/diffEnhancement');
    setEnhancedDiff(await highlightDiffMetadata(entry.summary));
  };

  return (
    <article
      ref={rowRef}
      id={`event-${entry.id}`}
      data-event-id={entry.id}
      className={`timeline-row timeline-row--${entry.kind}`}
      tabIndex={0}
      aria-label={`${kindLabels[entry.kind]} event: ${entry.title}`}
    >
      <div className="timeline-row__header">
        <span className="timeline-row__kind">{kindLabels[entry.kind]}</span>
        <strong>{entry.title}</strong>
        <time dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
      </div>

      {isCollapsed ? (
        <button className="timeline-row__reveal" type="button" onClick={() => setOpen(true)}>
          Specialist detail collapsed — show event
        </button>
      ) : (
        <>
          <p className="timeline-row__summary">{entry.summary}</p>
          {entry.kind === 'diff' && (
            <div className="timeline-row__diff">
              {enhancedDiff === null ? (
                <button type="button" onClick={loadDiffEnhancement}>Load syntax preview</button>
              ) : (
                <div className="timeline-row__highlight" dangerouslySetInnerHTML={{ __html: enhancedDiff }} />
              )}
            </div>
          )}
          {entry.relatedEventIds.length > 0 && (
            <nav className="timeline-row__links" aria-label="Correlated events">
              <span>Related:</span>
              {entry.relatedEventIds.map((eventId) => (
                <button key={eventId} type="button" onClick={() => onJumpToEvent(eventId)}>
                  {eventId}
                </button>
              ))}
            </nav>
          )}
        </>
      )}
    </article>
  );
};
