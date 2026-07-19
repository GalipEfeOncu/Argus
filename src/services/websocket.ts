import type { ArgusSessionCommand } from '@/types/events';
import type { ConnectionState } from './sessionProjection';
import { eventSimulator } from '@/services/eventSimulator';
import { syncLegacyProjection } from '@/services/legacyProjectionBridge';
import {
  SessionStreamClient,
  type SessionTransport,
  type TransportHandlers,
} from '@/services/sessionTransport';

const WS_BASE = 'ws://127.0.0.1:8000';

/** Live implementation of the same transport boundary used by EventSimulator. */
export class WebSocketSessionTransport implements SessionTransport {
  private socket: WebSocket | null = null;
  private intentionalClose = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  connect(sessionId: string, afterSequence: number, handlers: TransportHandlers): void {
    this.disconnect();
    this.intentionalClose = false;
    const socket = new WebSocket(`${WS_BASE}/ws/sessions/${encodeURIComponent(sessionId)}?after_sequence=${afterSequence}`);
    this.socket = socket;
    socket.onopen = () => handlers.onConnectionState('connected');
    socket.onmessage = (message) => {
      try {
        handlers.onEvent(JSON.parse(String(message.data)) as unknown);
      } catch {
        handlers.onEvent(null);
      }
    };
    socket.onclose = () => {
      if (this.socket === socket && !this.intentionalClose) {
        handlers.onConnectionState('reconnecting');
        this.reconnectTimer = setTimeout(() => handlers.onReconnectRequested(), 1_000);
      }
    };
    socket.onerror = () => {
      // onclose requests a reconnect and preserves the last applied sequence.
    };
  }

  disconnect(): void {
    this.intentionalClose = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close(1000, 'Client disconnect');
    this.socket = null;
  }

  send(command: ArgusSessionCommand): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(command));
    return true;
  }
}

class WebSocketManager {
  private client: SessionStreamClient | null = null;
  private sessionId: string | null = null;
  private unsubscribeProjection: (() => void) | null = null;

  connect(sessionId: string): void {
    this.sessionId = sessionId;
    if (eventSimulator.isActive(sessionId)) return;
    this.disconnect();
    this.client = new SessionStreamClient(new WebSocketSessionTransport(), sessionId);
    this.unsubscribeProjection = this.client.subscribe((projection) => syncLegacyProjection(sessionId, projection));
    this.client.connect();
  }

  sendMessage(content: string): void {
    if (this.sessionId !== null && eventSimulator.isActive(this.sessionId)) {
      eventSimulator.sendHumanMessage(this.sessionId, content);
      return;
    }
    this.send({ commandId: crypto.randomUUID(), type: 'message.send', payload: { content } });
  }

  sendApproval(approved: boolean, _feedback?: string): void {
    if (this.sessionId !== null && eventSimulator.isActive(this.sessionId)) {
      eventSimulator.resolveApproval(this.sessionId, approved);
      return;
    }
    this.send({
      commandId: crypto.randomUUID(),
      type: 'approval.resolve',
      payload: { approvalId: 'active-approval', resolution: approved ? 'approve' : 'reject' },
    });
  }

  sendInterrupt(): void {
    this.send({
      commandId: crypto.randomUUID(),
      type: 'participant.interrupt',
      payload: { participantId: 'active-participant', reasonSummary: 'Interrupted by the user.' },
    });
  }

  getConnectionState(): ConnectionState | null {
    return this.client?.getProjection().connection ?? null;
  }

  disconnect(): void {
    this.unsubscribeProjection?.();
    this.unsubscribeProjection = null;
    this.client?.disconnect();
    this.client = null;
  }

  private send(command: ArgusSessionCommand): void {
    this.client?.send(command);
  }
}

export const wsManager = new WebSocketManager();
