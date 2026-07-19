import type { ArgusSessionCommand, ArgusSessionEvent } from '@/types/events';

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

  next = projectEvent(next, event);
  return drainBufferedEvents(next, 'applied');
}

function drainBufferedEvents(state: SessionProjection, disposition: EventDisposition): EventReduction {
  const nextEvent = state.bufferedEvents[state.lastSequence + 1];
  if (nextEvent === undefined) return { state, disposition };

  const { [nextEvent.sequence]: _removed, ...remaining } = state.bufferedEvents;
  const reduced = applyOrderedEvent({ ...state, bufferedEvents: remaining }, nextEvent, JSON.stringify(nextEvent));
  return { ...reduced, disposition };
}

function projectEvent(state: SessionProjection, event: ArgusSessionEvent): SessionProjection {
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
      return { ...state, status: 'waiting_approval' };
    case 'decision.requested':
      return { ...state, status: 'waiting_decision' };
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
