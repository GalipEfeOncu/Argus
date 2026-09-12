import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { api } from '@/services/api';
import { tauriCommands } from '@/services/tauri';
import { useSettingsStore } from '@/stores/settingsStore';
import { useUIStore } from '@/stores/uiStore';
import { PROVIDER_PRESETS } from '@/types/provider';
import type { ModelInfo, ProviderPreset, ProviderProfile } from '@/types/provider';
import './Settings.css';

type LoadState = 'loading' | 'ready' | 'error';

function providerSaveError(error: unknown, stage: 'credential' | 'profile' | 'handoff'): string {
  const message = typeof error === 'string' ? error : error instanceof Error ? error.message : String(error);
  if (/credential store|credential could not be saved|store_provider_credential/i.test(message)) {
    return 'API key could not be saved in the operating-system credential store. Start the Argus desktop app and check the local keyring.';
  }
  if (/credential handoff|credential lookup|credential unavailable|credential reference/i.test(message)) {
    return 'The API key was saved, but the local runtime could not receive it. Restart Argus and retry.';
  }
  if (/backend is not ready|backend.*ready/i.test(message)) {
    return 'The local runtime stopped before the API key handoff. Retry after the runtime reconnects.';
  }
  if (/command .*not found|not implemented/i.test(message)) {
    return 'This desktop build does not include the credential-store command. Restart Argus from the latest build and retry.';
  }
  if (/api error 422/i.test(message)) {
    return 'The provider configuration was rejected. Check the preset and endpoint, then retry.';
  }
  if (stage === 'credential') {
    return 'The API key could not be saved in the operating-system credential store. Check the local keyring and retry.';
  }
  if (stage === 'profile') {
    return 'The provider profile could not be created. Check the local runtime and retry.';
  }
  if (stage === 'handoff') {
    return 'The provider was created, but its API key could not be handed to the local runtime. Restart Argus and retry.';
  }
  return 'Provider could not be saved. Check the credential and connection, then retry.';
}

export const Settings: React.FC = () => {
  const [providers, setProviders] = useState<ProviderProfile[]>([]);
  const settingsReturnPage = useUIStore((state) => state.settingsReturnPage);
  const setActivePage = useUIStore((state) => state.setActivePage);
  const defaultChatModel = useSettingsStore((state) => state.defaultChatModel);
  const setDefaultChatModel = useSettingsStore((state) => state.setDefaultChatModel);
  const addManualProviderModel = useSettingsStore((state) => state.addManualProviderModel);
  const [models, setModels] = useState<Record<string, ModelInfo[]>>({});
  const [modelStates, setModelStates] = useState<Record<string, LoadState>>({});
  const [modelQueries, setModelQueries] = useState<Record<string, string>>({});
  const [manualModels, setManualModels] = useState<Record<string, string>>({});
  const [providerPreset, setProviderPreset] = useState<ProviderPreset>('openai');
  const [displayName, setDisplayName] = useState('');
  const [credential, setCredential] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [catalogState, setCatalogState] = useState<LoadState>('loading');
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const selectedPreset = useMemo(
    () => PROVIDER_PRESETS.find((preset) => preset.id === providerPreset) ?? PROVIDER_PRESETS[0],
    [providerPreset],
  );
  const nativeCredentialStoreAvailable = isTauri();

  const discoverModels = useCallback(async (profile: ProviderProfile) => {
    setModelStates((current) => ({ ...current, [profile.id]: 'loading' }));
    try {
      const response = await api.providers.listModels(profile.id);
      setModels((current) => ({ ...current, [profile.id]: response.models }));
      setModelStates((current) => ({ ...current, [profile.id]: 'ready' }));
    } catch {
      setModelStates((current) => ({ ...current, [profile.id]: 'error' }));
    }
  }, []);

  const load = useCallback(async () => {
    setCatalogState('loading');
    setActionError(null);
    try {
      const profiles = await api.providers.list();
      setProviders(profiles);
      setCatalogState('ready');
      await Promise.all(profiles.filter((profile) => profile.credentialConfigured).map((profile) => tauriCommands.refreshProviderCredential(profile.id).catch(() => undefined)));
      await Promise.all(profiles.map(discoverModels));
    } catch {
      setCatalogState('error');
    }
  }, [discoverModels]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    setEndpoint(selectedPreset.endpoint ?? '');
    setCredential('');
  }, [selectedPreset]);

  const addProvider = async () => {
    if (!displayName || (selectedPreset.credentialRequired && !credential) || busy) return;
    if (selectedPreset.credentialRequired && !nativeCredentialStoreAvailable) {
      setActionError('API-key providers require the Argus desktop app because keys are stored in the operating-system credential store.');
      return;
    }
    setBusy(true); setActionError(null);
    let credentialReference: string | null = null;
    let createdProfileId: string | null = null;
    let stage: 'credential' | 'profile' | 'handoff' = selectedPreset.credentialRequired ? 'credential' : 'profile';
    try {
      if (selectedPreset.credentialRequired) credentialReference = await tauriCommands.storeProviderCredential(credential);
      stage = 'profile';
      const profile = await api.providers.create({
        providerKind: selectedPreset.providerKind,
        providerPreset: selectedPreset.id,
        displayName,
        endpoint: endpoint || null,
        credentialReference,
      });
      createdProfileId = profile.id;
      if (credentialReference) {
        stage = 'handoff';
        await tauriCommands.refreshProviderCredential(profile.id);
      }
      setProviders((current) => [...current, profile]);
      setDisplayName(''); setCredential('');
      await discoverModels(profile);
    } catch (error: unknown) {
      if (credentialReference) {
        if (createdProfileId) await api.providers.remove(createdProfileId).catch(() => undefined);
        await tauriCommands.deleteProviderCredential(credentialReference).catch(() => undefined);
      }
      setActionError(providerSaveError(error, stage));
    } finally { setBusy(false); }
  };

  const removeProvider = async (provider: ProviderProfile) => {
    setBusy(true); setActionError(null);
    try {
      const cleanupFailed = provider.credentialRequired !== false
        ? await tauriCommands.removeProviderCredential(provider.id).then(() => false).catch(() => true)
        : false;
      await api.providers.remove(provider.id);
      setProviders((current) => current.filter((item) => item.id !== provider.id));
      if (cleanupFailed) setActionError('Provider was removed, but its operating-system credential could not be cleaned up.');
    } catch { setActionError('Provider could not be removed.'); }
    finally { setBusy(false); }
  };

  const selectModel = (profile: ProviderProfile, model: ModelInfo) => {
    if (model.supportsChat === false) return;
    setDefaultChatModel({
      providerId: profile.id,
      modelId: model.id,
      displayName: `${profile.displayName} · ${model.displayName}`,
    });
  };

  const addManualModel = async (profile: ProviderProfile) => {
    const modelId = manualModels[profile.id]?.trim();
    if (!modelId) return;
    setActionError(null);
    try {
      const response = await api.providers.listModels(profile.id, modelId);
      setModels((current) => ({ ...current, [profile.id]: [...(current[profile.id] ?? []).filter((model) => model.id !== modelId), ...response.models] }));
      setModelStates((current) => ({ ...current, [profile.id]: 'ready' }));
      const model = response.models[0];
      if (model) {
        const modelRef = { providerId: profile.id, modelId: model.id, displayName: `${profile.displayName} · ${model.displayName} (manual; capabilities reviewed at runtime)` };
        addManualProviderModel(modelRef);
        setDefaultChatModel(modelRef);
      }
      setManualModels((current) => ({ ...current, [profile.id]: '' }));
    } catch { setActionError('The model ID could not be validated.'); }
  };

  const presetLabel = (preset: ProviderPreset | undefined) => PROVIDER_PRESETS.find((item) => item.id === preset)?.displayName ?? 'Custom';

  return <div className="settings-page"><div className="settings-inner">
    <div className="settings-header">
      <div><h1 className="settings-title">Provider Settings</h1><p className="settings-subtitle"><span>Manage provider credentials and discover available models.</span>{' '}<span>Browse every chat-capable model they expose.</span></p></div>
      {settingsReturnPage === 'new-chat' && <button type="button" className="settings-back-btn" onClick={() => setActivePage('new-chat')}>Back to chat</button>}
    </div>
    <section className="settings-card" aria-labelledby="providers-heading">
      <h2 id="providers-heading" className="settings-card-label">API PROVIDERS</h2>
      <p className="settings-description">API keys are saved in your operating system’s credential store. Argus only retains a non-secret reference. Ollama runs locally and does not require a key.</p>
      {!nativeCredentialStoreAvailable && <p className="settings-description">You are running the web development client. Ollama works locally here; API-key providers must be added from the Argus desktop app.</p>}
      {actionError && <p className="settings-error" role="alert">{actionError}</p>}
      {catalogState === 'loading' && providers.length === 0 && <div className="providers-empty" role="status">Loading configured providers…</div>}
      {catalogState === 'error' && <div className="settings-catalog-error" role="alert"><span>Configured providers could not be loaded from the local runtime.</span><button type="button" onClick={() => void load()}>Retry providers</button></div>}
      <div className="providers-list">{catalogState === 'ready' && providers.length === 0 ? <div className="providers-empty">No providers configured yet.</div> : providers.map((provider) => {
        const providerModels = models[provider.id] ?? [];
        const query = (modelQueries[provider.id] ?? '').trim().toLowerCase();
        const visibleModels = query === '' ? providerModels : providerModels.filter((model) => `${model.id} ${model.displayName}`.toLowerCase().includes(query));
        return <div key={provider.id} className="provider-row"><div className="provider-info">
          <div className="provider-name-row"><span className="provider-name">{provider.displayName}</span><span className="provider-type-badge">{presetLabel(provider.providerPreset)}</span></div>
          {provider.endpoint && <div className="provider-url">{provider.endpoint}</div>}
          <span className="provider-status">{provider.credentialRequired !== false ? `Credential ${provider.credentialConfigured ? 'configured' : 'required'}` : 'Local · no credential required'}</span>
          {modelStates[provider.id] === 'loading' && <span className="provider-status" role="status">Loading models…</span>}
          {modelStates[provider.id] === 'error' && <span className="provider-model-error" role="alert">Model catalogue unavailable. <button type="button" onClick={() => void discoverModels(provider)}>Retry models</button></span>}
          {providerModels.length > 0 && <div className="provider-model-browser">
            <div className="provider-model-browser-header"><strong>{providerModels.length} models</strong><input className="argus-input" aria-label={`${provider.displayName} model search`} value={modelQueries[provider.id] ?? ''} onChange={(event) => setModelQueries((current) => ({ ...current, [provider.id]: event.target.value }))} placeholder="Search models" /></div>
            <div className="provider-models" role="list" aria-label={`${provider.displayName} models`}>{visibleModels.map((model) => {
              const selected = defaultChatModel?.providerId === provider.id && defaultChatModel.modelId === model.id;
              const unavailable = model.supportsChat === false;
              return <div key={model.id} className="provider-model-item" role="listitem"><span className="provider-status">{model.displayName} · tools {model.supportsTools === true ? 'supported' : 'unknown'}{model.displayName !== model.id && ` · ${model.id}`}{unavailable ? ' · chat unsupported' : ''}</span><button type="button" className="provider-remove-btn" onClick={() => selectModel(provider, model)} disabled={unavailable}>{selected ? 'Selected' : 'Use for chat'}</button></div>;
            })}</div>
            {visibleModels.length === 0 && <span className="provider-status">No models match this search.</span>}
          </div>}
          <div className="provider-manual-model"><input className="argus-input" aria-label={`${provider.displayName} manual model ID`} value={manualModels[provider.id] ?? ''} onChange={(event) => setManualModels((current) => ({ ...current, [provider.id]: event.target.value }))} placeholder="Manual model ID" /><button type="button" className="provider-remove-btn" onClick={() => void addManualModel(provider)}>Use model</button></div>
        </div><button type="button" className="provider-remove-btn" onClick={() => void removeProvider(provider)} disabled={busy}>Remove</button></div>;
      })}</div>
      <div className="add-provider-form"><div className="add-provider-form-label">ADD NEW PROVIDER</div><div className="add-provider-grid">
        <div className="settings-field settings-field--full"><label className="settings-label" htmlFor="provider-kind">Provider</label><select id="provider-kind" className="argus-select" value={providerPreset} onChange={(event) => setProviderPreset(event.target.value as ProviderPreset)}>{PROVIDER_PRESETS.map((preset) => <option key={preset.id} value={preset.id}>{preset.displayName}{preset.credentialRequired ? '' : ' · local'}</option>)}</select></div>
        <div className="settings-field"><label className="settings-label" htmlFor="provider-name">Display Name</label><input id="provider-name" className="argus-input" value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></div>
        {selectedPreset.providerKind === 'openai_compat' && <div className="settings-field"><label className="settings-label" htmlFor="provider-endpoint">Base URL</label><input id="provider-endpoint" className="argus-input" value={endpoint} onChange={(event) => setEndpoint(event.target.value)} readOnly={providerPreset !== 'custom'} placeholder="https://provider.example/v1" /></div>}
        <div className="settings-field settings-field--full"><label className="settings-label" htmlFor="provider-key">API Key {selectedPreset.credentialRequired ? '' : '(not required)'}</label><input id="provider-key" className="argus-input" type="password" autoComplete="off" value={credential} onChange={(event) => setCredential(event.target.value)} disabled={!selectedPreset.credentialRequired} placeholder={selectedPreset.credentialRequired ? 'Stored in the OS credential service' : 'Ollama uses the local runtime'} /></div>
      </div><div className="add-provider-actions"><button type="button" className="settings-add-btn" onClick={() => void addProvider()} disabled={!displayName || (selectedPreset.credentialRequired && !credential) || busy}>{busy ? 'Saving…' : 'Add Provider'}</button></div></div>
    </section>
  </div></div>;
};
