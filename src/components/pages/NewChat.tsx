import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/services/api';
import { tauriCommands } from '@/services/tauri';
import { createConfiguration } from '@/services/sessionConfiguration';
import { useAgentStore } from '@/stores/agentStore';
import { useSessionStore } from '@/stores/sessionStore';
import { useSettingsStore } from '@/stores/settingsStore';
import { useUIStore } from '@/stores/uiStore';
import { useWorkspaceStore } from '@/stores/workspaceStore';
import type { AgentRole, ModelRef } from '@/types/agent';
import type { ModelInfo, ProviderProfile } from '@/types/provider';
import './NewChat.css';

type CatalogState = 'loading' | 'ready' | 'empty' | 'error';

interface ChatModelOption {
  profile: ProviderProfile;
  model: ModelInfo;
}

function modelKey(model: ModelRef): string {
  return model.providerId + ':' + model.modelId;
}

function toModelRef(option: ChatModelOption): ModelRef {
  return {
    providerId: option.profile.id,
    modelId: option.model.id,
    displayName: option.profile.displayName + ' · ' + option.model.displayName,
  };
}

export const NewChat: React.FC = () => {
  const { newChatDraft, setNewChatDraft, openSettings, setActivePage } = useUIStore();
  const defaultChatModel = useSettingsStore((state) => state.defaultChatModel);
  const manualProviderModels = useSettingsStore((state) => state.manualProviderModels);
  const setDefaultChatModel = useSettingsStore((state) => state.setDefaultChatModel);
  const createSession = useSessionStore((state) => state.createSession);
  const setActiveSession = useSessionStore((state) => state.setActiveSession);
  const initAgents = useAgentStore((state) => state.initAgents);
  const invalidateWorkspaceCatalog = useWorkspaceStore((state) => state.invalidate);
  const [options, setOptions] = useState<ChatModelOption[]>([]);
  const [selectedKey, setSelectedKey] = useState('');
  const [catalogState, setCatalogState] = useState<CatalogState>('loading');
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const attemptedModel = useRef<string | null>(null);

  const loadCatalog = useCallback(async () => {
    setCatalogState('loading');
    setCatalogError(null);
    try {
      const profiles = await api.providers.list();
      const configured = profiles.filter((profile) => profile.credentialRequired === false || profile.credentialConfigured);
      if (configured.length === 0) {
        setOptions([]);
        setCatalogState('empty');
        return;
      }
      await Promise.all(configured.map((profile) => tauriCommands.refreshProviderCredential(profile.id).catch(() => undefined)));
      const results = await Promise.allSettled(configured.map(async (profile) => ({
        profile,
        response: await api.providers.listModels(profile.id),
      })));
      const discoveredOptions = results.flatMap((result) => result.status === 'fulfilled'
        ? result.value.response.models.filter((model) => model.supportsChat !== false).map((model) => ({ profile: result.value.profile, model }))
        : []);
      const configuredIds = new Set(configured.map((profile) => profile.id));
      const knownKeys = new Set(discoveredOptions.map((option) => modelKey(toModelRef(option))));
      const manualOptions: ChatModelOption[] = manualProviderModels.flatMap((model) => {
        if (!configuredIds.has(model.providerId)) return [];
        const profile = configured.find((item) => item.id === model.providerId);
        if (profile === undefined) return [];
        const option: ChatModelOption = { profile, model: {
          id: model.modelId,
          displayName: model.modelId,
          source: 'manual',
        } };
        return knownKeys.has(modelKey(toModelRef(option))) ? [] : [option];
      });
      const nextOptions = [...discoveredOptions, ...manualOptions];
      setOptions(nextOptions);
      if (nextOptions.length === 0) {
        setCatalogState('error');
        setCatalogError('No usable model is available. Check the provider credential and model catalogue in Settings.');
      } else {
        setCatalogState('ready');
      }
    } catch {
      setOptions([]);
      setCatalogState('error');
      setCatalogError('The local provider catalogue could not be loaded. Make sure the backend is running, then retry.');
    }
  }, [manualProviderModels]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  useEffect(() => {
    if (options.length === 0) {
      setSelectedKey('');
      return;
    }
    const preferred = defaultChatModel === null ? undefined : options.find((option) => modelKey(toModelRef(option)) === modelKey(defaultChatModel));
    const selected = options.find((option) => modelKey(toModelRef(option)) === selectedKey) ?? preferred ?? options[0];
    const nextModel = toModelRef(selected);
    if (selectedKey !== modelKey(nextModel)) setSelectedKey(modelKey(nextModel));
  }, [defaultChatModel, options, selectedKey]);

  const selectedModel = useMemo(() => {
    const option = options.find((item) => modelKey(toModelRef(item)) === selectedKey);
    return option === undefined ? null : toModelRef(option);
  }, [options, selectedKey]);

  useEffect(() => {
    if (catalogState !== 'ready' || selectedModel === null || sessionId !== null || attemptedModel.current === modelKey(selectedModel)) return;
    attemptedModel.current = modelKey(selectedModel);
    setCreateError(null);
    void api.sessions.createChat(selectedModel).then((created) => {
      const configuration = { ...createConfiguration({ coordinator: selectedModel }), workspaceMode: 'snapshot' as const, availableAgentIds: [] };
      const roleConfigs = [{
        instanceId: 'coordinator',
        role: 'coordinator' as const,
        enabled: true,
        modelRef: selectedModel,
      }];
      const localId = createSession({
        kind: 'chat',
        projectPath: '',
        task: 'Direct conversation',
        name: created.name || 'New chat',
        roleConfigs,
        configuration,
      }, created.id);
      initAgents(created.agentSnapshots.flatMap((snapshot) => {
        const binding = snapshot.modelBinding;
        if (binding === null || binding === undefined) return [];
        return [{
          instanceId: snapshot.id,
          label: snapshot.name ?? 'Coordinator',
          role: snapshot.role as AgentRole,
          status: 'idle' as const,
          modelRef: { providerId: binding.providerProfileId, modelId: binding.modelId, displayName: selectedModel.displayName },
          tokenCount: 0,
        }];
      }));
      setDefaultChatModel(selectedModel);
      setSessionId(localId);
      setActiveSession(localId);
      invalidateWorkspaceCatalog();
      setActivePage('session');
    }).catch(() => {
      setCreateError('The direct chat could not be started. Check the local runtime and try again.');
    });
  }, [catalogState, createSession, initAgents, invalidateWorkspaceCatalog, selectedModel, sessionId, setActivePage, setActiveSession, setDefaultChatModel]);

  const handleModelChange = (value: string) => {
    setSelectedKey(value);
    const option = options.find((item) => modelKey(toModelRef(item)) === value);
    if (option !== undefined) setDefaultChatModel(toModelRef(option));
  };

  const retry = () => {
    attemptedModel.current = null;
    setCreateError(null);
    void loadCatalog();
  };

  return (
    <div className="new-chat-page">
      <main className="new-chat-body">
        <button type="button" className="new-chat-back new-chat-corner" onClick={() => setActivePage('dashboard')} aria-label="Go to dashboard">←</button>

        <section className="new-chat-welcome" aria-label="New direct chat">
          <p className="new-chat-eyebrow">DIRECT CHAT</p>
          <h1>What would you like to talk about?</h1>
          <p className="new-chat-description">Start writing immediately. This local chat does not use a project workspace or specialist team.</p>

          {options.length > 0 && (
            <label className="new-chat-model">
              <span>Model</span>
              <select value={selectedKey} onChange={(event) => handleModelChange(event.target.value)} aria-label="Chat model">
                {options.map((option) => {
                  const ref = toModelRef(option);
                  return <option key={modelKey(ref)} value={modelKey(ref)}>{ref.displayName}</option>;
                })}
              </select>
            </label>
          )}

          {catalogState === 'loading' && <p className="new-chat-status" role="status">Checking provider availability…</p>}
          {catalogState === 'error' && (
            <div className="new-chat-inline-state new-chat-inline-state--error" role="alert">
              <span>{catalogError}</span>
              <button type="button" onClick={retry}>Retry</button>
            </div>
          )}
          {catalogState === 'ready' && sessionId === null && createError === null && <p className="new-chat-status" role="status">Preparing your secure chat…</p>}
          {createError !== null && (
            <div className="new-chat-inline-state new-chat-inline-state--error" role="alert">
              <span>{createError}</span>
              <button type="button" onClick={retry}>Try again</button>
            </div>
          )}
        </section>

        <form className="new-chat-composer" onSubmit={(event) => event.preventDefault()}>
          <textarea
            aria-label="Message for direct chat"
            placeholder="Write a message…"
            value={newChatDraft}
            onChange={(event) => setNewChatDraft(event.target.value)}
            rows={4}
          />
          <div className="new-chat-composer-footer">
            <span>Enter to send · Shift+Enter for a new line</span>
            <button type="submit" disabled>Send message <span aria-hidden="true">↗</span></button>
          </div>
        </form>

        {catalogState === 'empty' && (
          <div className="new-chat-provider-hint" role="alert">
            <span className="new-chat-provider-dot" aria-hidden="true" />
            <strong>No provider configured</strong>
            <span className="new-chat-provider-copy">Add one in Settings to send.</span>
            <button type="button" onClick={() => openSettings('new-chat')}>Open Provider Settings</button>
          </div>
        )}
        {catalogState === 'error' && <p className="new-chat-provider-hint new-chat-provider-hint--error">Sending is locked until the local provider catalogue is ready.</p>}
      </main>
    </div>
  );
};
