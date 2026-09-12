import React, { useCallback, useEffect, useState } from 'react';
import { api } from '@/services/api';
import { tauriCommands } from '@/services/tauri';
import { useSettingsStore } from '@/stores/settingsStore';
import { useUIStore } from '@/stores/uiStore';
import type { ModelInfo, ProviderProfile, ProviderType } from '@/types/provider';
import './Settings.css';

type LoadState = 'loading' | 'ready' | 'error';

export const Settings: React.FC = () => {
  const [providers, setProviders] = useState<ProviderProfile[]>([]);
  const settingsReturnPage = useUIStore((state) => state.settingsReturnPage);
  const setActivePage = useUIStore((state) => state.setActivePage);
  const addManualProviderModel = useSettingsStore((state) => state.addManualProviderModel);
  const [models, setModels] = useState<Record<string, ModelInfo[]>>({});
  const [modelStates, setModelStates] = useState<Record<string, LoadState>>({});
  const [manualModels, setManualModels] = useState<Record<string, string>>({});
  const [providerType, setProviderType] = useState<ProviderType>('openai');
  const [displayName, setDisplayName] = useState('');
  const [credential, setCredential] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [catalogState, setCatalogState] = useState<LoadState>('loading');
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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

  const addProvider = async () => {
    if (!displayName || !credential || busy) return;
    setBusy(true); setActionError(null);
    let credentialReference: string | null = null;
    let createdProfileId: string | null = null;
    try {
      credentialReference = await tauriCommands.storeProviderCredential(credential);
      const profile = await api.providers.create({ providerKind: providerType, displayName, endpoint: endpoint || null, credentialReference });
      createdProfileId = profile.id;
      await tauriCommands.refreshProviderCredential(profile.id);
      setProviders((current) => [...current, profile]);
      setDisplayName(''); setCredential(''); setEndpoint('');
      await discoverModels(profile);
    } catch {
      if (credentialReference) {
        if (createdProfileId) await api.providers.remove(createdProfileId).catch(() => undefined);
        await tauriCommands.deleteProviderCredential(credentialReference).catch(() => undefined);
      }
      setActionError('Provider could not be saved. Check the credential and connection, then retry.');
    } finally { setBusy(false); }
  };

  const removeProvider = async (provider: ProviderProfile) => {
    setBusy(true); setActionError(null);
    try {
      const cleanupFailed = await tauriCommands.removeProviderCredential(provider.id).then(() => false).catch(() => true);
      await api.providers.remove(provider.id);
      setProviders((current) => current.filter((item) => item.id !== provider.id));
      if (cleanupFailed) setActionError('Provider was removed, but its operating-system credential could not be cleaned up.');
    } catch { setActionError('Provider could not be removed.'); }
    finally { setBusy(false); }
  };

  const addManualModel = async (profile: ProviderProfile) => {
    const modelId = manualModels[profile.id]?.trim();
    if (!modelId) return;
    setActionError(null);
    try {
      const response = await api.providers.listModels(profile.id, modelId);
      setModels((current) => ({ ...current, [profile.id]: response.models }));
      setModelStates((current) => ({ ...current, [profile.id]: 'ready' }));
      const model = response.models[0];
      if (model) addManualProviderModel({ providerId: profile.id, modelId: model.id, displayName: `${profile.displayName} · ${model.displayName} (manual; capabilities reviewed at runtime)` });
      setManualModels((current) => ({ ...current, [profile.id]: '' }));
    } catch { setActionError('The model ID could not be validated.'); }
  };

  return <div className="settings-page"><div className="settings-inner">
    <div className="settings-header">
      <div><h1 className="settings-title">Provider Settings</h1><p className="settings-subtitle">Manage provider credentials and discover available models.</p></div>
      {settingsReturnPage === 'new-chat' && <button type="button" className="settings-back-btn" onClick={() => setActivePage('new-chat')}>Back to chat</button>}
    </div>
    <section className="settings-card" aria-labelledby="providers-heading">
      <h2 id="providers-heading" className="settings-card-label">API PROVIDERS</h2>
      <p className="settings-description">API keys are saved in your operating system’s credential store. Argus only retains a non-secret reference.</p>
      {actionError && <p className="settings-error" role="alert">{actionError}</p>}
      {catalogState === 'loading' && providers.length === 0 && <div className="providers-empty" role="status">Loading configured providers…</div>}
      {catalogState === 'error' && <div className="settings-catalog-error" role="alert"><span>Configured providers could not be loaded from the local runtime.</span><button type="button" onClick={() => void load()}>Retry providers</button></div>}
      <div className="providers-list">{catalogState === 'ready' && providers.length === 0 ? <div className="providers-empty">No providers configured yet.</div> : providers.map((provider) => <div key={provider.id} className="provider-row"><div className="provider-info"><div className="provider-name-row"><span className="provider-name">{provider.displayName}</span><span className="provider-type-badge">{provider.providerKind}</span></div>{provider.endpoint && <div className="provider-url">{provider.endpoint}</div>}<span className="provider-status">Credential {provider.credentialConfigured ? 'configured' : 'required'}</span>
        {modelStates[provider.id] === 'loading' && <span className="provider-status" role="status">Loading models…</span>}
        {modelStates[provider.id] === 'error' && <span className="provider-model-error" role="alert">Model catalogue unavailable. <button type="button" onClick={() => void discoverModels(provider)}>Retry models</button></span>}
        <div className="provider-models">{(models[provider.id] ?? []).map((model) => <span key={model.id} className="provider-status">{model.displayName} · tools {model.supportsTools === true ? 'supported' : 'unknown'}</span>)}</div>
        <div className="provider-manual-model"><input className="argus-input" aria-label={`${provider.displayName} manual model ID`} value={manualModels[provider.id] ?? ''} onChange={(event) => setManualModels((current) => ({ ...current, [provider.id]: event.target.value }))} placeholder="Manual model ID" /><button type="button" className="provider-remove-btn" onClick={() => void addManualModel(provider)}>Use model</button></div></div><button type="button" className="provider-remove-btn" onClick={() => void removeProvider(provider)} disabled={busy}>Remove</button></div>)}</div>
      <div className="add-provider-form"><div className="add-provider-form-label">ADD NEW PROVIDER</div><div className="add-provider-grid">
        <div className="settings-field"><label className="settings-label" htmlFor="provider-kind">Provider Type</label><select id="provider-kind" className="argus-select" value={providerType} onChange={(event) => setProviderType(event.target.value as ProviderType)}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="google">Google Gemini</option><option value="openai_compat">OpenAI Compatible</option></select></div>
        <div className="settings-field"><label className="settings-label" htmlFor="provider-name">Display Name</label><input id="provider-name" className="argus-input" value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></div>
        <div className="settings-field settings-field--full"><label className="settings-label" htmlFor="provider-key">API Key</label><input id="provider-key" className="argus-input" type="password" autoComplete="off" value={credential} onChange={(event) => setCredential(event.target.value)} /></div>
        {providerType === 'openai_compat' && <div className="settings-field settings-field--full"><label className="settings-label" htmlFor="provider-endpoint">Base URL</label><input id="provider-endpoint" className="argus-input" value={endpoint} onChange={(event) => setEndpoint(event.target.value)} placeholder="https://provider.example/v1" /></div>}
      </div><div className="add-provider-actions"><button type="button" className="settings-add-btn" onClick={() => void addProvider()} disabled={!displayName || !credential || busy}>{busy ? 'Saving…' : 'Add Provider'}</button></div></div>
    </section>
  </div></div>;
};
