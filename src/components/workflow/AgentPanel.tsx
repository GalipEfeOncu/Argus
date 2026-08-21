import React, { useEffect, useRef } from 'react';
import { useSessionRoomStore } from '@/stores/sessionRoomStore';
import { useUIStore } from '@/stores/uiStore';
import { RuntimeContext } from './RuntimeContext';
import './AgentPanel.css';

function focusContextToggle(): void {
  window.requestAnimationFrame(() => document.getElementById('agent-panel-toggle')?.focus());
}

export const AgentPanel: React.FC<{ sessionId: string }> = ({ sessionId }) => {
  const projection = useSessionRoomStore((state) => state.projections[sessionId]);
  const agentPanelVisible = useUIStore((state) => state.agentPanelVisible);
  const setAgentPanelVisible = useUIStore((state) => state.setAgentPanelVisible);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const close = () => {
    setAgentPanelVisible(false);
    focusContextToggle();
  };

  useEffect(() => {
    if (!agentPanelVisible) return;
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setAgentPanelVisible(false);
      focusContextToggle();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [agentPanelVisible, setAgentPanelVisible]);

  if (!agentPanelVisible) return null;
  const connection = projection?.connection ?? 'connecting';
  const lifecycle = projection?.status ?? 'loading';

  return (
    <aside id="agent-context-panel" className="agent-panel-container animate-slide-in" aria-label="Session context" aria-describedby="agent-panel-status">
      <div className="agent-panel-header">
        <div>
          <h2 className="agent-panel-title">SESSION CONTEXT</h2>
          <p id="agent-panel-status" className="agent-panel-status" role="status">{connection} · {lifecycle.replaceAll('_', ' ')}</p>
        </div>
        <button ref={closeButtonRef} type="button" className="agent-panel-close" onClick={close} aria-label="Close session context">×</button>
      </div>
      <div className="agent-panel-scroll">
        <RuntimeContext sessionId={sessionId} />
      </div>
    </aside>
  );
};
