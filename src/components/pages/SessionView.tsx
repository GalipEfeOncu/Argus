import React from 'react';
import { useSessionStore } from '@/stores/sessionStore';
import { useUIStore } from '@/stores/uiStore';
import { useAgentStore } from '@/stores/agentStore';
import { ChatPanel } from '../chat/ChatPanel';
import { WorkflowMini } from '../workflow/WorkflowMini';
import { AgentCard } from '../chat/AgentCard';
import './SessionView.css';

export const SessionView: React.FC = () => {
  const { getActiveSession } = useSessionStore();
  const { agents } = useAgentStore();
  const { agentPanelVisible, workflowVisible } = useUIStore();
  
  const session = getActiveSession();

  if (!session) {
    return (
      <div className="flex items-center justify-center h-full w-full text-muted">
        No active session selected.
      </div>
    );
  }

  const activeAgents = Object.values(agents);

  return (
    <div className="session-view w-full h-full flex overflow-hidden">
      
      {/* Central Chat Panel */}
      <div className="flex-1 min-w-[400px] h-full relative z-10">
        <ChatPanel sessionId={session.id} />
      </div>

      {/* Right Sidebar (Workflow & Agents) */}
      {(workflowVisible || agentPanelVisible) && (
        <div className="right-panel w-80 min-w-[320px] flex flex-col border-l border-border-medium bg-bg-surface z-20">
          
          {workflowVisible && (
            <div className="workflow-container h-1/3 min-h-[250px] border-b border-border-medium relative">
              <WorkflowMini />
            </div>
          )}

          {agentPanelVisible && (
            <div className="agents-container flex-1 overflow-y-auto p-4 flex flex-col gap-3 glass">
              <h3 className="text-sm font-semibold text-secondary mb-2 uppercase tracking-widest sticky top-0 bg-bg-surface/80 backdrop-blur pb-2 z-10">
                Agent Status
              </h3>
              
              {activeAgents.length === 0 ? (
                <div className="text-muted text-sm text-center mt-4">Initializing agents...</div>
              ) : (
                activeAgents.map(agent => (
                  <AgentCard key={agent.role} agent={agent} />
                ))
              )}
            </div>
          )}
        </div>
      )}
      
    </div>
  );
};
