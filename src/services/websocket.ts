import type { ArgusSessionCommand } from '@/types/events';
import type { SessionConfigurationPatch } from '@/types/generated/session-commands';
import type { ConnectionState } from './sessionProjection';
import { eventSimulator } from '@/services/eventSimulator';
import { syncLegacyProjection } from '@/services/legacyProjectionBridge';
import { useSessionRoomStore } from '@/stores/sessionRoomStore';
import { clearBackendConnection, ensureBackendConnection } from '@/services/backendConnection';
import {
  SessionStreamClient,
  type SessionTransport,
  type TransportHandlers,
} from '@/services/sessionTransport';

/** Live implementation of the same transport boundary used by EventSimulator. */
export class WebSocketSessionTransport implements SessionTransport {
  private socket: WebSocket | null = null;
  private intentionalClose = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly pendingWireCommands: ArgusSessionCommand[] = [];
  private connectionGeneration = 0;

  connect(sessionId: string, afterSequence: number, handlers: TransportHandlers): void {
    this.disconnect();
    this.intentionalClose = false;
    // In the desktop shell this transparently wakes an idle sidecar. In a
    // browser development build the native invoke simply rejects and the
    // already-running development backend remains the transport source.
    const generation = ++this.connectionGeneration;
    void this.openAuthenticatedSocket(sessionId, afterSequence, handlers, generation);
  }

  private async openAuthenticatedSocket(sessionId: string, afterSequence: number, handlers: TransportHandlers, generation: number): Promise<void> {
    let connection;
    try {
      connection = await ensureBackendConnection();
    } catch {
      if (generation === this.connectionGeneration && !this.intentionalClose) {
        handlers.onConnectionState('reconnecting');
        this.reconnectTimer = setTimeout(() => handlers.onReconnectRequested(), 1_000);
      }
      return;
    }
    if (generation !== this.connectionGeneration || this.intentionalClose) return;
    const query = new URLSearchParams({ after_sequence: String(afterSequence) });
    const protocols = connection.accessToken.length > 0
      ? ['argus.v1', `argus.token.${connection.accessToken}`]
      : ['argus.v1'];
    const socket = new WebSocket(`${connection.websocketUrl}/ws/sessions/${encodeURIComponent(sessionId)}?${query}`, protocols);
    this.socket = socket;
    socket.onopen = () => {
      handlers.onConnectionState('connected');
      this.flushPendingCommands(socket);
    };
    socket.onmessage = (message) => {
      try {
        handlers.onEvent(JSON.parse(String(message.data)) as unknown);
      } catch {
        handlers.onEvent(null);
      }
    };
    socket.onclose = () => {
      if (this.socket === socket && !this.intentionalClose) {
        clearBackendConnection();
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
    this.connectionGeneration += 1;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close(1000, 'Client disconnect');
    this.socket = null;
  }

  send(command: ArgusSessionCommand): boolean {
    if (this.socket === null || this.socket.readyState === WebSocket.CLOSING || this.socket.readyState === WebSocket.CLOSED) return false;
    if (this.socket.readyState !== WebSocket.OPEN) {
      this.pendingWireCommands.push(command);
      return true;
    }
    this.socket.send(JSON.stringify(command));
    return true;
  }

  private flushPendingCommands(socket: WebSocket): void {
    while (this.pendingWireCommands.length > 0 && socket.readyState === WebSocket.OPEN) {
      const command = this.pendingWireCommands.shift();
      if (command !== undefined) socket.send(JSON.stringify(command));
    }
  }
}

class WebSocketManager {
  private client: SessionStreamClient | null = null;
  private sessionId: string | null = null;
  private unsubscribeProjection: (() => void) | null = null;
  private connectionConsumers = 0;

  connect(sessionId: string): void {
    if (this.sessionId === sessionId) {
      this.connectionConsumers += 1;
      return;
    }
    this.teardown();
    this.sessionId = sessionId;
    this.connectionConsumers = 1;
    if (eventSimulator.isActive(sessionId)) return;
    const client = new SessionStreamClient(new WebSocketSessionTransport(), sessionId);
    let startRequested = false;
    this.client = client;
    this.unsubscribeProjection = client.subscribe((projection, update) => {
      useSessionRoomStore.getState().publishProjection(sessionId, projection, update.isStreamingUpdate);
      syncLegacyProjection(sessionId, projection);
      if (!startRequested && projection.snapshot !== null && projection.status === 'created') {
        startRequested = true;
        client.send({ commandId: crypto.randomUUID(), type: 'session.start', payload: {} });
      }
    });
    client.connect();
  }

  sendMessage(content: string, mentionIds: string[] = []): void {
    if (this.sessionId !== null && eventSimulator.isActive(this.sessionId)) {
      eventSimulator.sendHumanMessage(this.sessionId, content, mentionIds);
      return;
    }
    this.send({ commandId: crypto.randomUUID(), type: 'message.send', payload: { content, ...(mentionIds.length === 0 ? {} : { mentionIds }) } });
  }

  sendApproval(approved: boolean, approvalId = 'active-approval'): void {
    if (this.sessionId !== null && eventSimulator.isActive(this.sessionId)) {
      eventSimulator.resolveApproval(this.sessionId, approved, approvalId);
      return;
    }
    const pending = this.sessionId === null ? undefined : useSessionRoomStore.getState().projections[this.sessionId]?.approvals[approvalId];
    this.send({
      commandId: crypto.randomUUID(),
      type: 'approval.resolve',
      payload: approved && pending !== undefined
        ? { approvalId, resolution: 'grant', grantCapabilities: [pending.capability], scopeSummary: pending.scopeSummary, grantScope: 'once' }
        : { approvalId, resolution: approved ? 'approve' : 'reject' },
    });
  }

  sendInterrupt(participantId?: string): void {
    if (this.sessionId !== null && eventSimulator.isActive(this.sessionId)) {
      eventSimulator.interruptActiveParticipant(this.sessionId, participantId);
      return;
    }
    const targetParticipantId = participantId ?? this.activeStreamingParticipantId();
    if (targetParticipantId === null) return;
    this.send({
      commandId: crypto.randomUUID(),
      type: 'participant.interrupt',
      payload: { participantId: targetParticipantId, reasonSummary: 'Interrupted by the user.' },
    });
  }

  controlSession(action: 'pause' | 'resume' | 'cancel'): void {
    if (this.sessionId !== null && eventSimulator.isActive(this.sessionId)) {
      eventSimulator.controlSession(this.sessionId, action);
      return;
    }
    const commandId = crypto.randomUUID();
    const command: ArgusSessionCommand = action === 'cancel'
      ? { commandId, type: 'session.cancel', payload: { reasonSummary: 'Cancelled by the user.' } }
      : { commandId, type: action === 'pause' ? 'session.pause' : 'session.resume', payload: {} };
    this.send(command);
  }

  updateConfiguration(configurationVersion: number, patch: SessionConfigurationPatch, confirmConsequences = false): void {
    if (this.sessionId !== null && eventSimulator.isActive(this.sessionId)) {
      eventSimulator.updateConfiguration(this.sessionId, configurationVersion, patch, confirmConsequences);
      return;
    }
    this.send({
      commandId: crypto.randomUUID(),
      type: 'session.configuration.update',
      payload: { expectedConfigurationVersion: configurationVersion, patch, confirmConsequences },
    });
  }

  resolveDecision(decisionId: string, choice: 'reassign' | 'change_approach' | 'deliver_partial' | 'stop'): void {
    if (this.sessionId !== null && eventSimulator.isActive(this.sessionId)) {
      eventSimulator.resolveDecision(this.sessionId, decisionId, choice);
      return;
    }
    this.send({ commandId: crypto.randomUUID(), type: 'decision.resolve', payload: { decisionId, choice, reasonSummary: 'Visible human decision.' } });
  }

  getConnectionState(): ConnectionState | null {
    return this.client?.getProjection().connection ?? null;
  }

  disconnect(sessionId: string): void {
    if (this.sessionId !== sessionId) return;
    this.connectionConsumers = Math.max(0, this.connectionConsumers - 1);
    if (this.connectionConsumers > 0) return;
    this.teardown();
  }

  private teardown(): void {
    this.unsubscribeProjection?.();
    this.unsubscribeProjection = null;
    this.client?.disconnect();
    this.client = null;
    this.sessionId = null;
    this.connectionConsumers = 0;
  }

  private send(command: ArgusSessionCommand): void {
    this.client?.send(command);
  }

  private activeStreamingParticipantId(): string | null {
    const projection = this.client?.getProjection();
    if (projection === undefined) return null;
    const streamingAuthor = Object.values(projection.messages).find((message) => message.streaming)?.authorId;
    if (streamingAuthor !== undefined) return streamingAuthor;
    return Object.values(projection.participants).find((participant) => participant.status === 'working')?.id ?? null;
  }
}

export const wsManager = new WebSocketManager();
