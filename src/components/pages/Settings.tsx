import React, { useCallback, useEffect, useState } from 'react';
import { api } from '@/services/api';
import { tauriCommands } from '@/services/tauri';
import { useSettingsStore } from '@/stores/settingsStore';
import type { ModelInfo, ProviderProfile, ProviderType } from '@/types/provider';
import './Settings.css';

export const Settings: React.FC = () => {
  const [providers, setProviders] = useState<ProviderProfile[]>([]);
  const addManualProviderModel = useSettingsStore((state) => state.addManualProviderModel);
  const [models, setModels] = useState<Record<string, ModelInfo[]>>({});
  const [manualModels, setManualModels] = useState<Record<string, string>>({});
  const [providerType, setProviderType] = useState<ProviderType>('openai');
  const [displayName, setDisplayName] = useState('');
  const [credential, setCredential] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const profiles = await api.providers.list();
      setProviders(profiles);
      await Promise.all(profiles.filter((profile) => profile.credentialConfigured).map((profile) => tauriCommands.refreshProviderCredential(profile.id).catch(() => undefined)));
      const discovered = await Promise.all(profiles.map(async (profile) => [profile.id, (await api.providers.listModels(profile.id)).models] as const));
      setModels(Object.fromEntries(discovered));
    } catch {
      setError('Provider listesi şu anda yüklenemedi.');
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const addProvider = async () => {
    if (!displayName || !credential || busy) return;
    setBusy(true); setError(null);
    let credentialReference: string | null = null;
    let createdProfileId: string | null = null;
    try {
      credentialReference = await tauriCommands.storeProviderCredential(credential);
      const profile = await api.providers.create({
        providerKind: providerType,
        displayName,
        endpoint: endpoint || null,
        credentialReference,
      });
      createdProfileId = profile.id;
      await tauriCommands.refreshProviderCredential(profile.id);
      setProviders((current) => [...current, profile]);
      setDisplayName(''); setCredential(''); setEndpoint('');
    } catch {
      if (credentialReference) {
        if (createdProfileId) await api.providers.remove(createdProfileId).catch(() => undefined);
        await tauriCommands.deleteProviderCredential(credentialReference).catch(() => undefined);
      }
      setError('Provider kaydedilemedi. Kimlik bilgisi veya bağlantıyı kontrol edin.');
    } finally { setBusy(false); }
  };

  const removeProvider = async (provider: ProviderProfile) => {
    setBusy(true); setError(null);
    try {
      const cleanupFailed = await tauriCommands.removeProviderCredential(provider.id).then(() => false).catch(() => true);
      await api.providers.remove(provider.id);
      setProviders((current) => current.filter((item) => item.id !== provider.id));
      if (cleanupFailed) setError('Provider kaldırıldı; işletim sistemi kimlik bilgisi daha sonra temizlenemedi.');
    } catch { setError('Provider kaldırılamadı.'); }
    finally { setBusy(false); }
  };

  const addManualModel = async (profile: ProviderProfile) => {
    const modelId = manualModels[profile.id]?.trim();
    if (!modelId) return;
    try {
      const response = await api.providers.listModels(profile.id, modelId);
      setModels((current) => ({ ...current, [profile.id]: response.models }));
      const model = response.models[0];
      if (model) addManualProviderModel({ providerId: profile.id, modelId: model.id, displayName: `${profile.displayName} · ${model.displayName} (manual; capabilities reviewed at runtime)` });
      setManualModels((current) => ({ ...current, [profile.id]: '' }));
    } catch { setError('Model kimliği doğrulanamadı.'); }
  };

  return <div className="settings-page"><div className="settings-inner">
    <div className="settings-header"><div><h1 className="settings-title">Settings</h1><p className="settings-subtitle">Manage providers and agent configuration</p></div></div>
    <section className="settings-card" aria-labelledby="providers-heading">
      <div id="providers-heading" className="settings-card-label">API PROVIDERS</div>
      <p className="settings-description">API keys are saved in your operating system’s credential store. Argus only retains a non-secret reference.</p>
      {error && <p className="settings-error" role="alert">{error}</p>}
      <div className="providers-list">{providers.length === 0 ? <div className="providers-empty">No providers configured yet.</div> : providers.map((provider) => <div key={provider.id} className="provider-row"><div className="provider-info"><div className="provider-name-row"><span className="provider-name">{provider.displayName}</span><span className="provider-type-badge">{provider.providerKind}</span></div>{provider.endpoint && <div className="provider-url">{provider.endpoint}</div>}<span className="provider-status">Credential {provider.credentialConfigured ? 'configured' : 'required'}</span><div className="provider-models">{(models[provider.id] ?? []).map((model) => <span key={model.id} className="provider-status">{model.displayName} · tools {model.supportsTools === true ? 'supported' : 'unknown'}</span>)}</div><div className="provider-manual-model"><input className="argus-input" aria-label={`${provider.displayName} manual model ID`} value={manualModels[provider.id] ?? ''} onChange={(event) => setManualModels((current) => ({ ...current, [provider.id]: event.target.value }))} placeholder="Manual model ID" /><button className="provider-remove-btn" onClick={() => void addManualModel(provider)}>Use model</button></div></div><button className="provider-remove-btn" onClick={() => void removeProvider(provider)} disabled={busy}>Remove</button></div>)}</div>
      <div className="add-provider-form"><div className="add-provider-form-label">ADD NEW PROVIDER</div><div className="add-provider-grid">
        <div className="settings-field"><label className="settings-label" htmlFor="provider-kind">Provider Type</label><select id="provider-kind" className="argus-select" value={providerType} onChange={(event) => setProviderType(event.target.value as ProviderType)}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="google">Google Gemini</option><option value="openai_compat">OpenAI Compatible</option></select></div>
        <div className="settings-field"><label className="settings-label" htmlFor="provider-name">Display Name</label><input id="provider-name" className="argus-input" value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></div>
        <div className="settings-field settings-field--full"><label className="settings-label" htmlFor="provider-key">API Key</label><input id="provider-key" className="argus-input" type="password" autoComplete="off" value={credential} onChange={(event) => setCredential(event.target.value)} /></div>
        {providerType === 'openai_compat' && <div className="settings-field settings-field--full"><label className="settings-label" htmlFor="provider-endpoint">Base URL</label><input id="provider-endpoint" className="argus-input" value={endpoint} onChange={(event) => setEndpoint(event.target.value)} placeholder="https://provider.example/v1" /></div>}
      </div><div className="add-provider-actions"><button className="settings-add-btn" onClick={() => void addProvider()} disabled={!displayName || !credential || busy}>Add Provider</button></div></div>
    </section>
  </div></div>;
};
