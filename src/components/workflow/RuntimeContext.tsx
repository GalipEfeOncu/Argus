import React, { useState } from 'react';
import { useSessionRoomStore } from '@/stores/sessionRoomStore';
import { useSessionStore } from '@/stores/sessionStore';
import { useWebSocket } from '@/hooks/useWebSocket';
import type { ProjectedParticipant } from '@/services/sessionProjection';
import type { SessionConfigurationPatch } from '@/types/generated/session-commands';
import { roleEvidence } from '@/services/sessionConfiguration';
import './RuntimeContext.css';

interface RuntimeContextProps {
  sessionId: string;
}

type ParticipantGroup = 'Available' | 'Active' | 'Waiting' | 'Done';
type LimitRow = [counter: string, ceiling: number | null];

function groupFor(status: ProjectedParticipant['status']): ParticipantGroup {
  if (status === 'idle') return 'Available';
  if (status === 'working') return 'Active';
  if (status === 'stopped' || status === 'errored') return 'Done';
  return 'Waiting';
}

function lifecycleLabel(status: string | null, error: { summary: string; recoverable: boolean } | null): string {
  if (status === 'completed') return 'Completed — all applicable gates are satisfied.';
  if (status === 'completed_partial') return 'Completed partially — unmet gates and limits remain visible in the timeline.';
  if (status === 'cancelled') return 'Cancelled — no further work will be dispatched.';
  if (status === 'failed') return error?.recoverable ? 'Recoverable failure — review the error and resume with a new action.' : 'Terminal failure — this session cannot continue.';
  if (status === 'waiting_approval') return 'Waiting for approval.';
  if (status === 'waiting_decision') return 'Waiting for a decision.';
  if (status === 'paused') return 'Paused — active work is held.';
  return status ?? 'Loading runtime state…';
}

export const RuntimeContext: React.FC<RuntimeContextProps> = ({ sessionId }) => {
  const projection = useSessionRoomStore((state) => state.projections[sessionId]);
  const configuration = useSessionStore((state) => state.sessions.find((session) => session.id === sessionId)?.configuration);
  const { sendInterrupt, sendApproval, controlSession, updateConfiguration, resolveDecision } = useWebSocket(sessionId);
  const [nextLimitResolution, setNextLimitResolution] = useState<'ask_user' | 'coordinator_decides' | 'stop'>('ask_user');
  const [draftAgentIds, setDraftAgentIds] = useState<string[] | null>(null);
  const [draftRequiredRules, setDraftRequiredRules] = useState<SessionConfigurationPatch['requiredRoleRules']>(null);
  const [draftApprovalBehavior, setDraftApprovalBehavior] = useState<NonNullable<SessionConfigurationPatch['approvalBehavior']> | null>(null);
  if (projection === undefined) return <section className="runtime-context" aria-label="Session runtime context">Loading runtime context…</section>;

  const grouped = Object.values(projection.participants).reduce<Record<ParticipantGroup, ProjectedParticipant[]>>(
    (groups, participant) => {
      groups[groupFor(participant.status)].push(participant);
      return groups;
    },
    { Available: [], Active: [], Waiting: [], Done: [] },
  );
  const canRecover = projection.status === 'failed' && projection.lastError?.recoverable === true;
  const isPaused = projection.status === 'paused' || canRecover;
  const terminal = ['completed', 'completed_partial', 'cancelled'].includes(projection.status ?? '')
    || (projection.status === 'failed' && !canRecover);
  const sessionControlPending = Object.values(projection.pendingCommands).some((entry) => ['session.pause', 'session.resume', 'session.cancel'].includes(entry.command.type));
  const configurationPending = Object.values(projection.pendingCommands).some((entry) => entry.command.type === 'session.configuration.update');
  const usage = Object.values(projection.usageByScope).reduce((total, value) => ({
    inputTokens: total.inputTokens + value.inputTokens,
    outputTokens: total.outputTokens + value.outputTokens,
    normalizedCost: total.normalizedCost + value.normalizedCost,
    durationMs: total.durationMs + value.durationMs,
  }), { inputTokens: 0, outputTokens: 0, normalizedCost: 0, durationMs: 0 });
  const selectedAgentIds = draftAgentIds ?? configuration?.availableAgentIds ?? [];
  const selectedRules = draftRequiredRules ?? configuration?.requiredRoleRules ?? [];
  const approvalBehavior = draftApprovalBehavior ?? configuration?.approvalPolicy.behavior ?? 'ask_by_policy';
  const configurationPatch: SessionConfigurationPatch = {
    availableAgentIds: selectedAgentIds,
    requiredRoleRules: selectedRules,
    approvalBehavior,
    limitResolution: nextLimitResolution,
  };
  const toggleFutureAgent = (agentId: string) => {
    setDraftAgentIds((current) => (current ?? selectedAgentIds).includes(agentId)
      ? (current ?? selectedAgentIds).filter((id) => id !== agentId)
      : [...(current ?? selectedAgentIds), agentId]);
  };
  const toggleFutureGate = (role: NonNullable<typeof configuration>['availableAgents'][number]['role']) => {
    setDraftRequiredRules((current) => {
      const rules = current ?? selectedRules;
      const existing = rules.find((rule) => rule.role === role);
      return existing === undefined
        ? [...rules, { id: `gate-${role}`, role, applicability: 'when_changes', successEvidence: roleEvidence(role), minimumCompletions: 1 }]
        : rules.filter((rule) => rule.id !== existing.id);
    });
  };

  return (
    <section className="runtime-context" aria-label="Session runtime context">
      <div className="runtime-context__heading"><h2>Runtime controls</h2><span aria-live="polite">{projection.status ?? 'loading'}</span></div>
      <p className="runtime-context__status">{lifecycleLabel(projection.status, projection.lastError)}</p>

      <div className="runtime-controls" aria-label="Session controls">
        {isPaused
          ? <button type="button" onClick={() => controlSession('resume')} disabled={terminal || sessionControlPending}>Resume</button>
          : <button type="button" onClick={() => controlSession('pause')} disabled={terminal || sessionControlPending}>Pause</button>}
        <button type="button" className="runtime-controls__cancel" onClick={() => controlSession('cancel')} disabled={terminal || sessionControlPending}>Cancel</button>
      </div>
      {Object.keys(projection.pendingCommands).length > 0 && <p className="runtime-context__pending" role="status">Command pending — waiting for the corresponding session event.</p>}

      <div className="runtime-groups">
        {(Object.keys(grouped) as ParticipantGroup[]).map((group) => <div key={group}><h3>{group} ({grouped[group].length})</h3>{grouped[group].length === 0 ? <p>None</p> : <ul>{grouped[group].map((participant) => <li key={participant.id}><span>{participant.id}</span>{group === 'Active' && <button type="button" onClick={() => sendInterrupt(participant.id)}>Interrupt</button>}<small>{participant.actionSummary ?? participant.status}</small></li>)}</ul>}</div>)}
      </div>

      <dl className="runtime-facts">
        <div><dt>Configuration</dt><dd>v{projection.configurationVersion}</dd></div>
        <div><dt>Current writer</dt><dd>{projection.currentWriter ?? 'None'}</dd></div>
        <div><dt>Active grants</dt><dd>{Object.values(projection.activeGrants).map((grant) => `${grant.capability} (${grant.scopeSummary})`).join(', ') || 'None'}</dd></div>
      </dl>
      {projection.status === 'completed_partial' && <div className="runtime-decision"><strong>Partial result details</strong><p>Unmet gates: {(configuration?.requiredRoleRules ?? []).filter((rule) => projection.gates[rule.id]?.status !== 'satisfied').map((rule) => rule.role).join(', ') || 'none recorded'}. Limits reached: {Object.values(projection.limits).filter((limit) => limit.hard).map((limit) => limit.counter).join(', ') || 'none recorded'}. Skipped verification: {(configuration?.requiredRoleRules ?? []).filter((rule) => projection.gates[rule.id]?.status !== 'satisfied').map((rule) => `${rule.role} evidence`).join(', ') || 'none recorded'}. Start a new assignment or session to resume.</p></div>}
      <div className="runtime-detail"><h3>Required gates</h3>{Object.values(projection.gates).length === 0 ? <p>No gate result yet.</p> : <ul>{Object.values(projection.gates).map((gate) => <li key={gate.id}>{gate.role}: {gate.status}{gate.evidence.length > 0 ? ` — ${gate.evidence.join('; ')}` : ''}</li>)}</ul>}</div>
      <div className="runtime-detail"><h3>Remaining limits</h3>{configuration === undefined ? <p>Configuration is loading.</p> : <ul>{([
        ['revisions', configuration.executionLimits.maxRevisionsPerFinding], ['assignment_attempts', configuration.executionLimits.maxAssignmentAttempts], ['model_iterations', configuration.executionLimits.maxModelIterationsPerAssignment], ['tool_calls', configuration.executionLimits.maxToolCallsPerAssignment], ['tokens', configuration.executionLimits.maxSessionTokens], ['cost', configuration.executionLimits.maxSessionCost], ['wall_clock_seconds', configuration.executionLimits.maxWallClockSeconds], ['parallel_read_only_assignments', configuration.executionLimits.maxParallelReadOnlyAssignments],
      ] as LimitRow[]).map(([counter, ceiling]) => {
        const observed = counter === 'tokens' ? usage.inputTokens + usage.outputTokens
          : counter === 'cost' ? usage.normalizedCost
            : counter === 'wall_clock_seconds' ? usage.durationMs / 1_000
              : counter === 'assignment_attempts' ? Math.max(projection.assignmentAttempts, projection.limits[counter]?.current ?? 0)
                : counter === 'tool_calls' ? Math.max(projection.toolCalls, projection.limits[counter]?.current ?? 0)
                  : counter === 'parallel_read_only_assignments' ? Object.values(projection.assignments).filter((assignment) => assignment.operationClass === 'read_only').length
                    : projection.limits[counter]?.current ?? 0;
        return <li key={counter}>{counter}: {ceiling === null ? 'unlimited user ceiling' : `${Math.max(0, Number(ceiling) - observed)} remaining of ${ceiling}`}{projection.limits[counter] === undefined ? '' : ` (${projection.limits[counter].hard ? 'hard' : 'warning'}; ${projection.limits[counter].resolution})`}</li>;
      })}</ul>}</div>

      <div className="runtime-detail"><h3>Update future configuration</h3><p>Changes apply only to future dispatches. Removing an active agent or reducing authority requires a server-provided consequence preview before the backend can accept it.</p>{configuration !== undefined && <><fieldset><legend>Future available team</legend>{configuration.availableAgents.map((agent) => <label key={agent.id}><input type="checkbox" checked={selectedAgentIds.includes(agent.id)} onChange={() => toggleFutureAgent(agent.id)} disabled={terminal || configurationPending} />{agent.label}</label>)}</fieldset><fieldset><legend>Future required gates</legend>{configuration.availableAgents.map((agent) => <label key={agent.id}><input type="checkbox" checked={selectedRules.some((rule) => rule.role === agent.role)} onChange={() => toggleFutureGate(agent.role)} disabled={terminal || configurationPending} />{agent.label}</label>)}</fieldset></>}<label>Approval behavior <select value={approvalBehavior} onChange={(event) => setDraftApprovalBehavior(event.target.value as NonNullable<SessionConfigurationPatch['approvalBehavior']>)} disabled={terminal || configurationPending}><option value="ask_by_policy">Ask by policy</option><option value="preauthorize_session">Pre-authorize session</option><option value="deny_interactive">Deny interactive</option></select></label><label>At a hard limit <select value={nextLimitResolution} onChange={(event) => setNextLimitResolution(event.target.value as 'ask_user' | 'coordinator_decides' | 'stop')} disabled={terminal || configurationPending}><option value="ask_user">Ask user</option><option value="coordinator_decides">Coordinator decides</option><option value="stop">Stop</option></select></label><button type="button" onClick={() => updateConfiguration(projection.configurationVersion, configurationPatch)} disabled={terminal || configurationPending}>Request consequence preview</button></div>
      {projection.configurationPreview !== null && <div className="runtime-decision"><strong>Server consequence preview</strong><p>{projection.configurationPreview.summary}</p><button type="button" onClick={() => updateConfiguration(projection.configurationVersion, projection.configurationPreview!.patch, true)} disabled={configurationPending}>Confirm and apply future configuration</button></div>}

      {Object.values(projection.approvals).map((approval) => { const pending = Object.values(projection.pendingCommands).some((entry) => entry.command.type === 'approval.resolve' && entry.command.payload.approvalId === approval.id); return <div className="runtime-decision" key={approval.id}><strong>Approval required: {approval.capability}</strong><p>{pending ? 'Decision pending — waiting for the session event.' : approval.scopeSummary}</p><button type="button" onClick={() => sendApproval(true, approval.id)} disabled={pending}>Approve</button><button type="button" onClick={() => sendApproval(false, approval.id)} disabled={pending}>Reject</button></div>; })}

      {Object.values(projection.decisions).map((decision) => { const pending = Object.values(projection.pendingCommands).some((entry) => entry.command.type === 'decision.resolve' && entry.command.payload.decisionId === decision.id); return <div className="runtime-decision" key={decision.id}><strong>Decision required</strong><p>{pending ? 'Decision pending — waiting for the session event.' : decision.reasonSummary}</p>{decision.choices.map((choice) => <button type="button" key={choice} disabled={pending} onClick={() => resolveDecision(decision.id, choice as 'reassign' | 'change_approach' | 'deliver_partial' | 'stop')}>{choice.replace('_', ' ')}</button>)}</div>; })}
    </section>
  );
};
