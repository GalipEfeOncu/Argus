import React, { useState } from 'react';
import type { ToolCallEvent } from '@/types/agent';
import { formatDuration } from '@/utils/formatters';
import './ToolCallBlock.css';

interface ToolCallBlockProps {
  toolCall: ToolCallEvent;
}

export const ToolCallBlock: React.FC<ToolCallBlockProps> = ({ toolCall }) => {
  const [expanded, setExpanded] = useState(false);

  const isRunning = toolCall.status === 'running' || toolCall.status === 'pending';
  const isError = toolCall.status === 'error';

  let statusIcon = '🔄';
  if (toolCall.status === 'success') statusIcon = '✅';
  if (isError) statusIcon = '❌';

  return (
    <div className={`tool-call-block glass-surface ${isRunning ? 'tool-running' : ''} ${isError ? 'tool-error' : ''}`}>
      <div 
        className="tool-call-header flex justify-between items-center cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <span className={`tool-icon ${isRunning ? 'spin' : ''}`}>{statusIcon}</span>
          <span className="tool-name font-mono text-sm font-semibold text-primary">{toolCall.tool}</span>
          <span className="tool-args text-xs text-muted truncate max-w-[200px]">
            {JSON.stringify(toolCall.args)}
          </span>
        </div>
        <div className="flex items-center gap-3">
          {toolCall.duration !== undefined && (
            <span className="text-xs text-muted">{formatDuration(toolCall.duration)}</span>
          )}
          <span className="text-muted text-xs">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>
      
      {expanded && (
        <div className="tool-call-details">
          <div className="tool-args-full mb-2">
            <div className="text-xs text-muted mb-1 uppercase tracking-wider">Arguments</div>
            <pre className="text-xs font-mono bg-black/40 p-2 rounded border border-white/5 overflow-auto">
              {JSON.stringify(toolCall.args, null, 2)}
            </pre>
          </div>
          {toolCall.result && (
            <div className="tool-result">
              <div className="text-xs text-muted mb-1 uppercase tracking-wider">Result</div>
              <pre className="text-xs font-mono bg-black/40 p-2 rounded border border-white/5 overflow-auto max-h-[300px]">
                {toolCall.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
