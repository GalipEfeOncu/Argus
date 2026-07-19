import Ajv from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import sessionEventsSchema from '../../contracts/session-events.schema.json';
import type { ArgusSessionCommand, ArgusSessionEvent } from '@/types/events';
import {
  createSessionProjection,
  queueCommand,
  reduceSessionEvent,
  setConnectionState,
  type ConnectionState,
  type SessionProjection,
} from './sessionProjection';

export interface TransportHandlers {
  onEvent(value: unknown): void;
  onConnectionState(state: ConnectionState): void;
  onReconnectRequested(): void;
}

export interface SessionTransport {
  connect(sessionId: string, afterSequence: number, handlers: TransportHandlers): void;
  disconnect(): void;
  send(command: ArgusSessionCommand): boolean;
}

export interface StreamClock {
  setTimeout(callback: () => void, delayMs: number): ReturnType<typeof setTimeout>;
  clearTimeout(timer: ReturnType<typeof setTimeout>): void;
}

export interface ProjectionUpdate {
  isStreamingUpdate: boolean;
}

const browserClock: StreamClock = {
  setTimeout: (callback, delayMs) => setTimeout(callback, delayMs),
  clearTimeout: (timer) => clearTimeout(timer),
};

export class SessionStreamClient {
  private projection: SessionProjection;
  private gapTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly listeners = new Set<(projection: SessionProjection, update: ProjectionUpdate) => void>();

  constructor(
    private readonly transport: SessionTransport,
    private readonly sessionId: string,
    private readonly clock: StreamClock = browserClock,
    private readonly gapTimeoutMs = 5_000,
  ) {
    this.projection = createSessionProjection(sessionId);
  }

  connect(): void {
    this.transport.connect(this.sessionId, this.projection.lastSequence, this.transportHandlers());
  }

  disconnect(): void {
    this.clearGapTimer();
    this.transport.disconnect();
    this.projection = setConnectionState(this.projection, 'idle');
    this.publish({ isStreamingUpdate: false });
  }

  getProjection(): SessionProjection {
    return this.projection;
  }

  subscribe(listener: (projection: SessionProjection, update: ProjectionUpdate) => void): () => void {
    this.listeners.add(listener);
    listener(this.projection, { isStreamingUpdate: false });
    return () => this.listeners.delete(listener);
  }

  send(command: ArgusSessionCommand): boolean {
    this.projection = queueCommand(this.projection, command);
    this.publish({ isStreamingUpdate: false });
    return this.transport.send(command);
  }

  retry(commandId: string): boolean {
    const pending = this.projection.pendingCommands[commandId];
    return pending === undefined ? false : this.send(pending.command);
  }

  private transportHandlers(): TransportHandlers {
    return {
      onEvent: (value) => this.receive(value),
      onConnectionState: (connection) => {
        this.projection = setConnectionState(this.projection, connection);
        this.publish({ isStreamingUpdate: false });
      },
      onReconnectRequested: () => this.resync(),
    };
  }

  private receive(value: unknown): void {
    const event = parseSessionEvent(value);
    if (event === null) {
      this.projection = { ...this.projection, connection: 'resyncing', resyncReason: 'invalid_payload' };
      this.publish({ isStreamingUpdate: false });
      this.resync();
      return;
    }

    const result = reduceSessionEvent(this.projection, event);
    this.projection = result.state;
    this.publish({ isStreamingUpdate: event.type === 'message.delta' });
    if (result.disposition === 'buffered') this.armGapTimer();
    if (result.disposition === 'applied' && Object.keys(this.projection.bufferedEvents).length === 0) this.clearGapTimer();
    if (result.disposition === 'resync_required') this.resync();
  }

  private armGapTimer(): void {
    if (this.gapTimer !== null) return;
    this.gapTimer = this.clock.setTimeout(() => {
      this.gapTimer = null;
      if (Object.keys(this.projection.bufferedEvents).length === 0) return;
      this.projection = { ...this.projection, connection: 'resyncing', resyncReason: 'sequence_gap' };
      this.publish({ isStreamingUpdate: false });
      this.resync();
    }, this.gapTimeoutMs);
  }

  private clearGapTimer(): void {
    if (this.gapTimer === null) return;
    this.clock.clearTimeout(this.gapTimer);
    this.gapTimer = null;
  }

  private resync(): void {
    this.clearGapTimer();
    this.transport.disconnect();
    this.transport.connect(this.sessionId, this.projection.lastSequence, this.transportHandlers());
  }

  private publish(update: ProjectionUpdate): void {
    this.listeners.forEach((listener) => listener(this.projection, update));
  }
}

/** Test and simulator transport that uses the same untrusted-wire boundary as WebSocket. */
export class InMemorySessionTransport implements SessionTransport {
  private handlers: TransportHandlers | null = null;
  readonly sentCommands: ArgusSessionCommand[] = [];
  readonly connections: Array<{ sessionId: string; afterSequence: number }> = [];

  connect(sessionId: string, afterSequence: number, handlers: TransportHandlers): void {
    this.connections.push({ sessionId, afterSequence });
    this.handlers = handlers;
    handlers.onConnectionState('connected');
  }

  disconnect(): void {
    this.handlers = null;
  }

  send(command: ArgusSessionCommand): boolean {
    this.sentCommands.push(command);
    return this.handlers !== null;
  }

  emit(event: ArgusSessionEvent | unknown): void {
    this.handlers?.onEvent(event);
  }
}

const eventValidator = new Ajv({
  allErrors: true,
  strict: false,
});
addFormats(eventValidator);
const validateSessionEvent = eventValidator.compile(sessionEventsSchema);

/** Validates untrusted WebSocket data against the generated Pydantic schema. */
export function parseSessionEvent(value: unknown): ArgusSessionEvent | null {
  return validateSessionEvent(value) ? value as ArgusSessionEvent : null;
}
