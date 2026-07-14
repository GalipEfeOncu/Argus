import type { WSEvent } from '@/types/session';
import type { ToolCallEvent, DiffBlock } from '@/types/agent';
import { useAgentStore } from '@/stores/agentStore';
import { useSessionStore } from '@/stores/sessionStore';
import { eventSimulator } from '@/services/eventSimulator';

const WS_BASE = 'ws://127.0.0.1:8000';

class WebSocketManager {
  private ws: WebSocket | null = null;
  private sessionId: string | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private currentMsgId: string | null = null;

  connect(sessionId: string): void {
    this.sessionId = sessionId;
    if (eventSimulator.isActive(sessionId)) return;
    this.cleanup();
    
    const url = `${WS_BASE}/ws/session/${sessionId}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log('[WS] Connected to session', sessionId);
    };

    this.ws.onmessage = (evt) => {
      try {
        const event: WSEvent = JSON.parse(evt.data as string);
        this.handleEvent(event);
      } catch (err) {
        console.error('[WS] Failed to parse event', err);
      }
    };

    this.ws.onclose = (evt) => {
      console.log('[WS] Disconnected', evt.code, evt.reason);
      if (evt.code !== 1000) {
        // Unexpected close — attempt reconnect
        this.reconnectTimer = setTimeout(() => this.connect(sessionId), 3000);
      }
    };

    this.ws.onerror = (err) => {
      console.error('[WS] Error', err);
    };
  }

  send(data: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    } else {
      console.warn('[WS] Cannot send — socket not open');
    }
  }

  sendMessage(content: string): void {
    if (this.sessionId && eventSimulator.isActive(this.sessionId)) {
      eventSimulator.sendHumanMessage(this.sessionId, content);
      return;
    }
    this.send({ type: 'user_message', content });
  }

  sendApproval(approved: boolean, feedback?: string): void {
    if (this.sessionId && eventSimulator.isActive(this.sessionId)) {
      eventSimulator.resolveApproval(this.sessionId, approved);
      return;
    }
    this.send({ type: 'human_response', approved, feedback });
  }

  sendInterrupt(): void {
    this.send({ type: 'interrupt' });
  }

  disconnect(): void {
    this.cleanup();
  }

  private cleanup(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
  }

  private handleEvent(event: WSEvent): void {
    const agentStore = useAgentStore.getState();
    const sessionStore = useSessionStore.getState();

    switch (event.type) {
      case 'agent_start': {
        agentStore.updateAgentStatus(
          event.agentRole!,
          'thinking',
          `Starting ${event.agentRole}...`
        );
        // Create a new message bubble for this agent
        this.currentMsgId = agentStore.addMessage({
          role: 'agent',
          agentRole: event.agentRole,
          content: '',
          isStreaming: true,
          timestamp: event.timestamp,
        });
        break;
      }

      case 'token': {
        if (this.currentMsgId && event.content) {
          agentStore.appendStreamToken(this.currentMsgId, event.content);
          agentStore.updateAgentStatus(event.agentRole!, 'streaming');
        }
        break;
      }

      case 'agent_done': {
        if (this.currentMsgId) {
          agentStore.finalizeMessage(this.currentMsgId);
          this.currentMsgId = null;
        }
        agentStore.updateAgentStatus(event.agentRole!, 'done');
        break;
      }

      case 'tool_call_start': {
        const toolCall = event.data as unknown as ToolCallEvent;
        if (this.currentMsgId) {
          agentStore.addToolCallToMessage(this.currentMsgId, {
            ...toolCall,
            status: 'running',
          });
        }
        agentStore.updateAgentStatus(event.agentRole!, 'using_tool', toolCall.tool);
        break;
      }

      case 'tool_call_result': {
        const { toolCallId, result, duration } = event.data as {
          toolCallId: string; result: string; duration: number;
        };
        if (this.currentMsgId) {
          agentStore.updateToolCall(this.currentMsgId, toolCallId, {
            result,
            duration,
            status: 'success',
          });
        }
        break;
      }

      case 'diff': {
        const diff = event.data as unknown as DiffBlock;
        if (this.currentMsgId) {
          // Attach diff to current message
          // We'll update the message to include diffBlocks
          console.log('[WS] Diff received for', diff.filePath);
        }
        break;
      }

      case 'interrupt': {
        const { reason, message } = event.data as { reason: string; message: string };
        agentStore.setInterrupted(true, reason || message);
        sessionStore.updateSessionStatus(this.sessionId!, 'waiting_approval');
        break;
      }

      case 'session_complete': {
        sessionStore.updateSessionStatus(this.sessionId!, 'completed');
        break;
      }

      case 'error': {
        console.error('[WS] Backend error:', event.data);
        sessionStore.updateSessionStatus(this.sessionId!, 'error');
        break;
      }
    }
  }
}

// Singleton instance
export const wsManager = new WebSocketManager();
