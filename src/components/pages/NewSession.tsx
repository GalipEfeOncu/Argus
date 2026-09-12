import React from 'react';
import { useUIStore } from '@/stores/uiStore';
import './NewSession.css';

export const NewSession: React.FC = () => {
  const { setActivePage } = useUIStore();
  return <div className="new-session-page"><div className="new-session-shell">
    <header className="new-session-heading"><p>START A NEW SESSION</p><h1>Start a new session</h1><span>Choose a focused chat or configure a bounded project session.</span></header>
    <div className="new-session-options">
      <button type="button" className="new-session-option new-session-option--chat" onClick={() => setActivePage('new-chat')}>
        <span><strong>New Chat</strong><small>Start a focused conversation without a project or agent team.</small><em>Open direct chat →</em></span>
      </button>
      <button type="button" className="new-session-option" onClick={() => setActivePage('session-setup')}>
        <span><strong>New Project Session</strong><small>Give the Coordinator a goal and choose a bounded specialist team.</small><em>Configure project session →</em></span>
      </button>
    </div>
  </div></div>;
};
