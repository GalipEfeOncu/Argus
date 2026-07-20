import React from 'react';
import { useAgentStore } from '@/stores/agentStore';
import { useUIStore } from '@/stores/uiStore';
import type { AgentStatus, AgentRole } from '@/types/agent';
import './AgentPanel.css';

/* ── Role-specific SVG icons ──────────────────────────────── */

const PlannerIcon: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
    <line x1="16" y1="2" x2="16" y2="6" />
    <line x1="8" y1="2" x2="8" y2="6" />
    <line x1="3" y1="10" x2="21" y2="10" />
    <line x1="8" y1="14" x2="13" y2="14" />
  </svg>
);

const BuilderIcon: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="16 18 22 12 16 6" />
    <polyline points="8 6 2 12 8 18" />
    <line x1="12" y1="2" x2="12" y2="22" opacity="0.5" />
  </svg>
);

const ReviewerIcon: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  </svg>
);

const TesterIcon: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v11a1 1 0 0 0 1 1h4a1 1 0 0 0 1-1V3M3 9a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2" />
  </svg>
);

const UIAgentIcon: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="4 17 10 11 4 5" />
    <line x1="12" y1="19" x2="20" y2="19" />
  </svg>
);

const roleIconMap: Record<string, React.FC> = {
  coordinator: PlannerIcon,
  planner: PlannerIcon,
  builder: BuilderIcon,
  reviewer: ReviewerIcon,
  tester: TesterIcon,
  ui_agent: UIAgentIcon,
};

const RoleIcon: React.FC<{ role: string }> = ({ role }) => {
  const Icon = roleIconMap[role] ?? PlannerIcon;
  return <Icon />;
};

/* ── Check icon for done nodes ─────────────────────────────── */
const CheckIcon: React.FC = () => (
  <svg width="8" height="8" fill="none" stroke="currentColor" strokeWidth="3" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12" />
  </svg>
);

interface AgentPanelItem {
  id: string;
  role: AgentRole;
  label: string;
  subtitle: string;
  status: AgentStatus;
  action: string;
  tokens: number;
}

export const AgentPanel: React.FC = () => {
  const { agents } = useAgentStore();
  const { agentPanelVisible } = useUIStore();
  const activeAgents = Object.values(agents);

  const displayAgents: AgentPanelItem[] = activeAgents.map((agent) => ({
    id: agent.instanceId ?? agent.role,
    role: agent.role,
    label: agent.label ?? (agent.role.charAt(0).toUpperCase() + agent.role.slice(1)),
    subtitle: agent.role.replace('_', ' ').toUpperCase(),
    status: agent.status,
    action: agent.currentAction || 'Idle',
    tokens: agent.tokenCount,
  }));

  if (!agentPanelVisible) return null;

  return (
    <aside className="agent-panel-container flex flex-col select-none animate-slide-in">

      {/* ── Panel Header ─────────────────────────────────── */}
      <div className="agent-panel-header">
        <h2 className="agent-panel-title">
          AGENTS
        </h2>
        <span className="live-badge">
          <span className="live-pulse-dot" />
          LIVE
        </span>
      </div>

      {/* ── Agent Cards ──────────────────────────────────── */}
      <div className="agents-list flex flex-col gap-2 overflow-y-auto agents-cards-scroll flex-1 min-h-0">
        {displayAgents.map((agent) => {
          const isThinking = agent.status === 'thinking' || agent.status === 'streaming' || agent.status === 'using_tool';
          const isDone = agent.status === 'done';
          const highlight = isThinking || agent.status === 'waiting_approval';

          return (
            <div
              key={agent.id}
              className={`agent-card ${highlight ? 'agent-card--active' : ''} ${isDone ? 'agent-card--done' : ''}`}
            >
              {/* Card top row */}
              <div className="agent-card-header">
                <div className="agent-card-identity">
                  <div className={`agent-icon-box agent-icon-box--${agent.role}`}>
                    <RoleIcon role={agent.role} />
                  </div>
                  <div className="agent-info">
                    <span className="agent-name">{agent.label}</span>
                    <span className="agent-subtitle">{agent.subtitle}</span>
                  </div>
                </div>
                {/* Status dot */}
                <span
                  className={`agent-status-dot ${
                    highlight
                      ? 'agent-status-dot--active'
                      : isDone
                        ? 'agent-status-dot--done'
                        : 'agent-status-dot--idle'
                  }`}
                  title={agent.status}
                />
              </div>

              {/* Action text */}
              <p className="agent-action-text">{agent.action}</p>

              {/* Token count */}
              {agent.tokens > 0 && (
                <span className="agent-token-count">{agent.tokens.toLocaleString()} tokens</span>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Pipeline Flow Timeline ───────────────────────── */}
      <div className="pipeline-section">
        <h3 className="pipeline-title">SESSION ACTIVITY</h3>

        <div className="pipeline-timeline">
          {/* Vertical line */}
          <div className="pipeline-line" />

          {displayAgents.map((agent) => {
            const isDone = agent.status === 'done';
            const isActive = agent.status === 'thinking' || agent.status === 'streaming' || agent.status === 'using_tool' || agent.status === 'waiting_approval';

            return (
              <div key={agent.id} className="pipeline-node">
                {/* Node circle */}
                <div className={`pipeline-node-circle ${
                  isDone
                    ? 'pipeline-node-circle--done'
                    : isActive
                      ? 'pipeline-node-circle--active'
                      : 'pipeline-node-circle--idle'
                }`}>
                  {isDone ? (
                    <CheckIcon />
                  ) : isActive ? (
                    <span className="pipeline-node-letter">
                      {agent.label.charAt(0)}
                    </span>
                  ) : null}
                </div>

                <span className={`pipeline-node-label ${
                  isDone ? 'pipeline-node-label--done' : isActive ? 'pipeline-node-label--active' : 'pipeline-node-label--idle'
                }`}>
                  {agent.label}
                </span>

                <span className={`pipeline-node-status ${
                  isDone ? 'pipeline-node-status--done' : isActive ? 'pipeline-node-status--active' : 'pipeline-node-status--idle'
                }`}>
                  {isDone ? 'Done' : isActive ? 'Active' : 'Pending'}
                </span>

              </div>
            );
          })}
        </div>
      </div>

      {/* ── Halt All Agents ──────────────────────────────── */}
      <div className="halt-section">
        <button
          className="halt-btn"
          onClick={() => console.log('HALT ALL AGENTS')}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
          </svg>
          <span>Halt All Agents</span>
        </button>
      </div>

    </aside>
  );
};
