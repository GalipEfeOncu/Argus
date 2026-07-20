import { create } from 'zustand';
import type { AgentInfo, AgentStatus, Message, ToolCallEvent } from '@/types/agent';

interface AgentStoreState {
  agents: Record<string, AgentInfo>;    // keyed by immutable agent instance ID
  messages: Message[];
  isInterrupted: boolean;
  interruptReason?: string;

  initAgents: (infos: AgentInfo[]) => void;
  updateAgentStatus: (agentId: string, status: AgentStatus, action?: string) => void;
  addMessage: (msg: Message | Omit<Message, 'id'>) => string;
  appendStreamToken: (msgId: string, token: string) => void;
  finalizeMessage: (msgId: string) => void;
  addToolCallToMessage: (msgId: string, toolCall: ToolCallEvent) => void;
  updateToolCall: (msgId: string, toolCallId: string, updates: Partial<ToolCallEvent>) => void;
  setInterrupted: (interrupted: boolean, reason?: string) => void;
  clearSession: () => void;
  incrementTokenCount: (agentId: string, count: number) => void;
}

export const useAgentStore = create<AgentStoreState>()((set) => ({
  agents: {},
  messages: [],
  isInterrupted: false,
  interruptReason: undefined,

  initAgents: (infos) => {
    const agents: Record<string, AgentInfo> = {};
    infos.forEach((info) => { agents[info.instanceId ?? info.role] = info; });
    set({ agents, messages: [], isInterrupted: false });
  },

      updateAgentStatus: (agentId, status, action) => {
    set((s) => ({
      agents: {
        ...s.agents,
        [agentId]: { ...s.agents[agentId], status, currentAction: action },
      },
    }));
  },

  addMessage: (msg) => {
    const fullMsg: Message = 'id' in msg ? msg : { ...msg, id: crypto.randomUUID() };
    set((s) => ({ messages: [...s.messages, fullMsg] }));
    return fullMsg.id;
  },

  appendStreamToken: (msgId, token) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === msgId ? { ...m, content: m.content + token } : m
      ),
    }));
  },

  finalizeMessage: (msgId) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === msgId ? { ...m, isStreaming: false } : m
      ),
    }));
  },

  addToolCallToMessage: (msgId, toolCall) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === msgId
          ? { ...m, toolCalls: [...(m.toolCalls ?? []), toolCall] }
          : m
      ),
    }));
  },

  updateToolCall: (msgId, toolCallId, updates) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === msgId
          ? {
              ...m,
              toolCalls: (m.toolCalls ?? []).map((tc) =>
                tc.id === toolCallId ? { ...tc, ...updates } : tc
              ),
            }
          : m
      ),
    }));
  },

  setInterrupted: (interrupted, reason) => {
    set({ isInterrupted: interrupted, interruptReason: reason });
  },

  clearSession: () => {
    set({ agents: {}, messages: [], isInterrupted: false, interruptReason: undefined });
  },

  incrementTokenCount: (agentId, count) => {
    set((s) => ({
      agents: {
        ...s.agents,
        [agentId]: { ...s.agents[agentId], tokenCount: (s.agents[agentId]?.tokenCount ?? 0) + count },
      },
    }));
  },
}));
