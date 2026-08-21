import React, { useEffect, useState } from 'react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useSessionRoomStore } from '@/stores/sessionRoomStore';
import './MessageInput.css';

interface MessageInputProps {
  sessionId: string;
}

export const MessageInput: React.FC<MessageInputProps> = ({ sessionId }) => {
  const [content, setContent] = useState('');
  const [submission, setSubmission] = useState<{ commandId: string; draft: string } | null>(null);
  const [dispatchError, setDispatchError] = useState<string | null>(null);
  const { sendMessage, sendInterrupt } = useWebSocket(sessionId);
  const projection = useSessionRoomStore((state) => state.projections[sessionId]);
  const isStreaming = Object.values(projection?.messages ?? {}).some((message) => message.streaming);
  const connection = projection?.connection ?? 'idle';
  const waitingForApproval = projection?.status === 'waiting_approval';
  const dispatchAvailable = connection === 'connected';
  const mentions = extractMentions(content);
  const targetLabel = mentions.length === 0 ? 'Coordinator' : mentions.join(', ');

  useEffect(() => {
    if (submission === null || projection === undefined) return;
    const result = projection.events.find((event) => event.correlationId === submission.commandId);
    if (result?.type === 'message.created') {
      setContent((current) => current === submission.draft ? '' : current);
      setSubmission(null);
      setDispatchError(null);
    } else if (result?.type === 'error.created') {
      setSubmission(null);
      setDispatchError(result.payload.summary);
    }
  }, [projection, submission]);

  const handleSend = () => {
    if (!content.trim() || !dispatchAvailable || submission !== null) return;
    const draft = content;
    const result = sendMessage(content.trim(), mentions);
    if (result.status === 'unavailable') {
      setDispatchError('The message was not sent. Keep editing and try again after the connection recovers.');
      return;
    }
    setDispatchError(null);
    setSubmission({ commandId: result.commandId, draft });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
    if (e.key === 'Escape' && isStreaming) {
      e.preventDefault();
      sendInterrupt();
    }
  };

  return (
    <div className="input-section">

      {/* ── Input Box ───────────────────────────────────── */}
      <div className="input-box-container">

        <textarea
          className="input-textarea"
          rows={3}
          aria-label="Message for shared room"
          placeholder="Describe your task; @name explicitly targets a participant"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={handleKeyDown}
        />

        {/* ── Bottom Row ──────────────────────────────────── */}
        <div className="input-bottom-row">

          {/* Execute button */}
          <button
            className="btn-execute"
            onClick={handleSend}
            disabled={!content.trim() || !dispatchAvailable || submission !== null}
            type="button"
          >
            <span>Execute Task</span>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polyline points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
      </div>

      <p className="composer-target">Targets: {targetLabel}{isStreaming ? ' · Escape interrupts active streaming' : ''}</p>
      {waitingForApproval && <p className="composer-state">Approval is still pending. You can message Coordinator; sending a message does not approve or reject the request.</p>}
      {connection === 'reconnecting' && <p className="composer-state" role="status">Reconnecting… Keep editing; sending resumes after the connection recovers.</p>}
      {connection === 'resyncing' && <p className="composer-state" role="status">Restoring ordered session state… Keep editing; sending resumes when it is ready.</p>}
      {submission !== null && <p className="composer-state" role="status">Message pending — waiting for its canonical room event.</p>}
      {dispatchError !== null && <p className="composer-state composer-state--error" role="alert">{dispatchError}</p>}

    </div>
  );
};

const knownMentionPattern = /@([a-z][a-z0-9_-]*)/gi;

export function extractMentions(content: string): string[] {
  const values = new Set<string>();
  for (const match of content.matchAll(knownMentionPattern)) values.add(match[1].toLowerCase());
  return [...values];
}
