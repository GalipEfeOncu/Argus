import type { ArgusSessionCommand, ArgusSessionEvent } from '@/types/events';
import type { SessionConfigurationPatch } from '@/types/generated/session-commands';

export type ConnectionState = 'idle' | 'connected' | 'reconnecting' | 'resyncing';
export type ResyncReason = 'conflicting_event' | 'conflicting_sequence' | 'invalid_payload' | 'sequence_gap' | 'session_mismatch';

export interface ProjectedMessage {
  id: string;
  authorId: string;
  authorKind: 'human' | 'system' | 'coordinator' | 'agent';
  content: string;
  streaming: boolean;
  timestamp: string;
}

export interface ProjectedParticipant {
  id: string;
  kind: 'human' | 'system' | 'coordinator' | 'agent';
  status: 'idle' | 'working' | 'waiting' | 'paused' | 'errored' | 'stopped';
  actionSummary?: string;
}

export interface PendingCommand {
  command: ArgusSessionCommand;
  attempts: number;
}

export interface ProjectedGate {
  id: string;
  role: string;
  status: string;
  evidence: string[];
}

export interface ProjectedLimit {
  counter: string;
  current: number;
  threshold: number;
  hard: boolean;
  resolution: string;
}

export interface ProjectedApproval {
  id: string;
  capability: string;
  scopeSummary: string;
  assignmentId?: string;
}

export interface ProjectedDecision {
  id: string;
  scopeId: string;
  choices: string[];
  reasonSummary: string;
}

export interface ProjectedUsage {
  inputTokens: number;
  outputTokens: number;
  normalizedCost: number;
  durationMs: number;
}

interface ProjectedAssignment {
  id: string;
  assigneeAgentId: string;
  operationClass: 'read_only' | 'mutating';
}

export interface SessionProjection {
  sessionId: string | null;
  status: string | null;
  lastSequence: number;
  connection: ConnectionState;
  resyncReason: ResyncReason | null;
  events: ArgusSessionEvent[];
  snapshot: Extract<ArgusSessionEvent, { type: 'session.snapshot' }> | null;
  messages: Record<string, ProjectedMessage>;
  participants: Record<string, ProjectedParticipant>;
  eventFingerprints: Record<string, string>;
  bufferedEvents: Record<number, ArgusSessionEvent>;
  pendingCommands: Record<string, PendingCommand>;
  configurationVersion: number;
  gates: Record<string, ProjectedGate>;
  limits: Record<string, ProjectedLimit>;
  activeGrants: Record<string, { capability: string; scopeSummary: string }>;
  approvals: Record<string, ProjectedApproval>;
  decisions: Record<string, ProjectedDecision>;
  assignments: Record<string, ProjectedAssignment>;
  currentWriter: string | null;
  lastError: { summary: string; recoverable: boolean } | null;
  usageByScope: Record<string, ProjectedUsage>;
  assignmentAttempts: number;
  toolCalls: number;
  lastAcceptedConfigurationPatch: SessionConfigurationPatch | null;
  configurationPreview: { patch: SessionConfigurationPatch; summary: string } | null;
}

export type EventDisposition = 'applied' | 'buffered' | 'ignored' | 'resync_required';

export interface EventReduction {
  state: SessionProjection;
  disposition: EventDisposition;
}

export function createSessionProjection(sessionId: string | null = null): SessionProjection {
  return {
    sessionId,
    status: null,
    lastSequence: 0,
    connection: 'idle',
    resyncReason: null,
    events: [],
    snapshot: null,
    messages: {},
    participants: {},
    eventFingerprints: {},
    bufferedEvents: {},
    pendingCommands: {},
    configurationVersion: 1,
    gates: {},
    limits: {},
    activeGrants: {},
    approvals: {},
    decisions: {},
    assignments: {},
    currentWriter: null,
    lastError: null,
    usageByScope: {},
    assignmentAttempts: 0,
    toolCalls: 0,
    lastAcceptedConfigurationPatch: null,
    configurationPreview: null,
  };
}

export function setConnectionState(state: SessionProjection, connection: ConnectionState): SessionProjection {
  return { ...state, connection };
}

export function queueCommand(state: SessionProjection, command: ArgusSessionCommand): SessionProjection {
  const existing = state.pendingCommands[command.commandId];
  return {
    ...state,
    pendingCommands: {
      ...state.pendingCommands,
      [command.commandId]: { command, attempts: (existing?.attempts ?? 0) + 1 },
    },
  };
}

/**
 * Applies a validated event without performing I/O.  Sequence gaps are retained
 * until their predecessor arrives; the stream client owns the gap timeout.
 */
export function reduceSessionEvent(state: SessionProjection, event: ArgusSessionEvent): EventReduction {
  if (state.sessionId !== null && event.sessionId !== state.sessionId) {
    return requireResync(state, 'session_mismatch');
  }

  const fingerprint = JSON.stringify(event);
  const knownFingerprint = state.eventFingerprints[event.eventId];
  if (knownFingerprint !== undefined) {
    return knownFingerprint === fingerprint
      ? { state, disposition: 'ignored' }
      : requireResync(state, 'conflicting_event');
  }

  if (event.type === 'session.snapshot') {
    return reduceSnapshot(state, event, fingerprint);
  }

  if (event.sequence <= state.lastSequence) {
    return requireResync(state, 'conflicting_sequence');
  }

  const bufferedAtSequence = state.bufferedEvents[event.sequence];
  if (bufferedAtSequence !== undefined) {
    return sameEvent(bufferedAtSequence, event)
      ? { state, disposition: 'ignored' }
      : requireResync(state, 'conflicting_sequence');
  }

  if (event.sequence !== state.lastSequence + 1) {
    return {
      state: {
        ...state,
        sessionId: state.sessionId ?? event.sessionId,
        bufferedEvents: { ...state.bufferedEvents, [event.sequence]: event },
      },
      disposition: 'buffered',
    };
  }

  return applyOrderedEvent(state, event, fingerprint);
}

function reduceSnapshot(
  state: SessionProjection,
  event: Extract<ArgusSessionEvent, { type: 'session.snapshot' }>,
  fingerprint: string,
): EventReduction {
  if (event.payload.lastSequence < state.lastSequence) {
    return { state, disposition: 'ignored' };
  }

  const next: SessionProjection = {
    ...state,
    sessionId: state.sessionId ?? event.sessionId,
    status: event.payload.status,
    snapshot: event,
    resyncReason: null,
    eventFingerprints: { ...state.eventFingerprints, [event.eventId]: fingerprint },
    pendingCommands: resolveCommand(state.pendingCommands, event.correlationId),
  };
  return drainBufferedEvents(next, 'applied');
}

function applyOrderedEvent(
  state: SessionProjection,
  event: ArgusSessionEvent,
  fingerprint: string,
): EventReduction {
  let next: SessionProjection = {
    ...state,
    sessionId: state.sessionId ?? event.sessionId,
    lastSequence: event.sequence,
    events: [...state.events, event],
    eventFingerprints: { ...state.eventFingerprints, [event.eventId]: fingerprint },
    pendingCommands: resolveCommand(state.pendingCommands, event.correlationId),
  };

  next = projectEvent(next, event, state.pendingCommands[event.correlationId ?? '']?.command);
  return drainBufferedEvents(next, 'applied');
}

function drainBufferedEvents(state: SessionProjection, disposition: EventDisposition): EventReduction {
  const nextEvent = state.bufferedEvents[state.lastSequence + 1];
  if (nextEvent === undefined) return { state, disposition };

  const { [nextEvent.sequence]: _removed, ...remaining } = state.bufferedEvents;
  const reduced = applyOrderedEvent({ ...state, bufferedEvents: remaining }, nextEvent, JSON.stringify(nextEvent));
  return { ...reduced, disposition };
}

function projectEvent(state: SessionProjection, event: ArgusSessionEvent, correlatedCommand?: ArgusSessionCommand): SessionProjection {
  switch (event.type) {
    case 'session.status_changed':
      return { ...state, status: event.payload.status };
    case 'participant.status_changed':
      return {
        ...state,
        participants: {
          ...state.participants,
          [event.payload.participantId]: {
            id: event.payload.participantId,
            kind: event.payload.participantKind,
            status: event.payload.status,
            ...(event.payload.actionSummary === undefined || event.payload.actionSummary === null
              ? {}
              : { actionSummary: event.payload.actionSummary }),
          },
        },
      };
    case 'message.created':
      return {
        ...state,
        messages: {
          ...state.messages,
          [event.payload.messageId]: {
            id: event.payload.messageId,
            authorId: event.payload.authorId,
            authorKind: event.payload.authorKind,
            content: event.payload.content,
            streaming: event.payload.streaming ?? false,
            timestamp: event.timestamp,
          },
        },
      };
    case 'message.delta': {
      const message = state.messages[event.payload.messageId];
      return message === undefined
        ? state
        : {
            ...state,
            messages: {
              ...state.messages,
              [message.id]: { ...message, content: message.content + event.payload.delta, streaming: true },
            },
          };
    }
    case 'message.completed': {
      const message = state.messages[event.payload.messageId];
      return message === undefined
        ? state
        : { ...state, messages: { ...state.messages, [message.id]: { ...message, streaming: false } } };
    }
    case 'approval.requested':
      return {
        ...state,
        status: 'waiting_approval',
        approvals: {
          ...state.approvals,
          [event.payload.approvalId]: {
            id: event.payload.approvalId,
            capability: event.payload.capability,
            scopeSummary: event.payload.scopeSummary,
            ...(event.payload.assignmentId === null || event.payload.assignmentId === undefined ? {} : { assignmentId: event.payload.assignmentId }),
          },
        },
      };
    case 'approval.resolved': {
      const approval = state.approvals[event.payload.approvalId];
      const { [event.payload.approvalId]: _resolved, ...approvals } = state.approvals;
      return {
        ...state,
        approvals,
        activeGrants: event.payload.grantId === null || event.payload.grantId === undefined || approval === undefined
          ? state.activeGrants
          : { ...state.activeGrants, [event.payload.grantId]: { capability: approval.capability, scopeSummary: approval.scopeSummary } },
      };
    }
    case 'decision.requested':
      return {
        ...state,
        status: 'waiting_decision',
        decisions: {
          ...state.decisions,
          [event.payload.decisionId]: {
            id: event.payload.decisionId,
            scopeId: event.payload.scopeId,
            choices: [...event.payload.choices],
            reasonSummary: event.payload.reasonSummary,
          },
        },
      };
    case 'decision.recorded': {
      const { [event.payload.decisionId]: _resolved, ...decisions } = state.decisions;
      return { ...state, decisions };
    }
    case 'session.configuration_updated':
      return {
        ...state,
        configurationVersion: event.payload.configurationVersion,
        lastAcceptedConfigurationPatch: correlatedCommand?.type === 'session.configuration.update' ? correlatedCommand.payload.patch : state.lastAcceptedConfigurationPatch,
        configurationPreview: null,
      };
    case 'gate.status_changed':
      return {
        ...state,
        gates: {
          ...state.gates,
          [event.payload.gateId]: {
            id: event.payload.gateId,
            role: event.payload.role,
            status: event.payload.status,
            evidence: (event.payload.evidence ?? []).map((item) => item.summary),
          },
        },
      };
    case 'limit.warning':
    case 'limit.reached':
      return {
        ...state,
        limits: {
          ...state.limits,
          [event.payload.counter]: {
            counter: event.payload.counter,
            current: event.payload.current,
            threshold: event.payload.threshold,
            hard: event.payload.hard,
            resolution: event.payload.resolution,
          },
        },
      };
    case 'assignment.created':
      return {
        ...state,
        assignments: {
          ...state.assignments,
          [event.payload.assignmentId]: {
            id: event.payload.assignmentId,
            assigneeAgentId: event.payload.assigneeAgentId,
            operationClass: event.payload.operationClass,
          },
        },
        currentWriter: event.payload.operationClass === 'mutating' ? event.payload.assigneeAgentId : state.currentWriter,
        assignmentAttempts: state.assignmentAttempts + 1,
      };
    case 'tool.requested':
      return { ...state, toolCalls: state.toolCalls + 1 };
    case 'assignment.completed':
    case 'assignment.failed':
    case 'assignment.cancelled': {
      const assignment = state.assignments[event.payload.assignmentId];
      const { [event.payload.assignmentId]: _finished, ...assignments } = state.assignments;
      return {
        ...state,
        assignments,
        currentWriter: assignment?.operationClass === 'mutating' ? null : state.currentWriter,
      };
    }
    case 'error.created':
      return {
        ...state,
        lastError: { summary: event.payload.summary, recoverable: event.payload.recoverable },
        configurationPreview: event.payload.code === 'configuration_preview_required' && correlatedCommand?.type === 'session.configuration.update'
          ? { patch: correlatedCommand.payload.patch, summary: event.payload.summary }
          : state.configurationPreview,
      };
    case 'usage.updated':
      return {
        ...state,
        usageByScope: {
          ...state.usageByScope,
          [event.payload.scopeId]: {
            inputTokens: event.payload.inputTokens,
            outputTokens: event.payload.outputTokens,
            normalizedCost: event.payload.normalizedCost,
            durationMs: event.payload.durationMs,
          },
        },
      };
    default:
      return state;
  }
}

function requireResync(state: SessionProjection, reason: ResyncReason): EventReduction {
  return {
    state: { ...state, connection: 'resyncing', resyncReason: reason },
    disposition: 'resync_required',
  };
}

function resolveCommand(
  pendingCommands: Record<string, PendingCommand>,
  correlationId: string | null | undefined,
): Record<string, PendingCommand> {
  if (correlationId === undefined || correlationId === null || pendingCommands[correlationId] === undefined) {
    return pendingCommands;
  }
  const { [correlationId]: _resolved, ...remaining } = pendingCommands;
  return remaining;
}

function sameEvent(left: ArgusSessionEvent, right: ArgusSessionEvent): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}
