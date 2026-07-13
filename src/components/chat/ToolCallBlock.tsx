import React, { useState } from 'react';
import type { ToolCallEvent } from '@/types/agent';
import { formatDuration } from '@/utils/formatters';
import './ToolCallBlock.css';

interface ToolCallBlockProps {
  toolCall: ToolCallEvent;
}

const SpinnerIcon: React.FC = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
    <path d="M21 12a9 9 0 1 1-6.219-8.56" />
  </svg>
);

const CheckIcon: React.FC = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12" />
  </svg>
);

const XIcon: React.FC = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

const ChevronDownIcon: React.FC = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
    <polyline points="6 9 12 15 18 9" />
  </svg>
);

export const ToolCallBlock: React.FC<ToolCallBlockProps> = ({ toolCall }) => {
  const [expanded, setExpanded] = useState(false);

  const isRunning = toolCall.status === 'running' || toolCall.status === 'pending';
  const isError   = toolCall.status === 'error';
  const isSuccess = toolCall.status === 'success';

  const statusClass = isRunning ? 'tool-running' : isError ? 'tool-error' : isSuccess ? 'tool-success' : '';
  const iconClass   = isRunning ? 'tool-status-icon--running' : isError ? 'tool-status-icon--error' : 'tool-status-icon--success';

  return (
    <div className={`tool-call-block ${statusClass}`}>
      <div
        className="tool-call-header"
        onClick={() => setExpanded(!expanded)}
      >
        {/* Left: status icon + name + args preview */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, flex: 1 }}>
          <span className={`tool-status-icon ${iconClass}`}>
            {isRunning ? <SpinnerIcon /> : isError ? <XIcon /> : <CheckIcon />}
          </span>
          <span className="tool-name">{toolCall.tool}</span>
          <span className="tool-args-preview">
            {JSON.stringify(toolCall.args)}
          </span>
        </div>

        {/* Right: duration + chevron */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
          {toolCall.duration !== undefined && (
            <span className="tool-duration">{formatDuration(toolCall.duration)}</span>
          )}
          <span className={`tool-expand-chevron ${expanded ? 'tool-expand-chevron--open' : ''}`}>
            <ChevronDownIcon />
          </span>
        </div>
      </div>

      {expanded && (
        <div className="tool-call-details">
          <div>
            <div className="tool-detail-label">Arguments</div>
            <pre className="tool-detail-pre">{JSON.stringify(toolCall.args, null, 2)}</pre>
          </div>
          {toolCall.result && (
            <div>
              <div className="tool-detail-label">Result</div>
              <pre className="tool-detail-pre">{toolCall.result}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
