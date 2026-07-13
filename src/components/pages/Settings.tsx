import React, { useState } from 'react';
import { useSettingsStore } from '@/stores/settingsStore';
import './Settings.css';

export const Settings: React.FC = () => {
  const { providers, addProvider, removeProvider } = useSettingsStore();

  const [newProviderType, setNewProviderType] = useState('openai_compat');
  const [newProviderName, setNewProviderName] = useState('');
  const [newApiKey, setNewApiKey] = useState('');
  const [newBaseUrl, setNewBaseUrl] = useState('');

  const handleAddProvider = () => {
    if (!newProviderName || !newApiKey) return;
    addProvider({
      name: newProviderName,
      type: newProviderType as any,
      apiKey: newApiKey,
      baseUrl: newBaseUrl || undefined,
    });
    setNewProviderName('');
    setNewApiKey('');
    setNewBaseUrl('');
  };

  return (
    <div className="settings-page">
      <div className="settings-inner">

        {/* ── Header ──────────────────────────────────────── */}
        <div className="settings-header">
          <div className="settings-header-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9" />
            </svg>
          </div>
          <div>
            <h1 className="settings-title">Settings</h1>
            <p className="settings-subtitle">Manage providers and agent configuration</p>
          </div>
        </div>

        {/* ── API Providers ────────────────────────────────── */}
        <div className="settings-card">
          <div className="settings-card-label">API PROVIDERS</div>
          <p className="settings-description">
            Add your API keys to power the agents. Keys are stored locally in your app storage.
          </p>

          {/* Provider list */}
          <div className="providers-list">
            {providers.length === 0 ? (
              <div className="providers-empty">
                No providers configured yet.
              </div>
            ) : (
              providers.map(p => (
                <div key={p.id} className="provider-row">
                  <div className="provider-info">
                    <div className="provider-name-row">
                      <span className="provider-name">{p.name}</span>
                      <span className="provider-type-badge">{p.type}</span>
                    </div>
                    {p.baseUrl && <div className="provider-url">{p.baseUrl}</div>}
                  </div>
                  <button
                    className="provider-remove-btn"
                    onClick={() => removeProvider(p.id)}
                    title="Remove provider"
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
                    </svg>
                    Remove
                  </button>
                </div>
              ))
            )}
          </div>

          {/* Add new provider */}
          <div className="add-provider-form">
            <div className="add-provider-form-label">ADD NEW PROVIDER</div>

            <div className="add-provider-grid">
              <div className="settings-field">
                <label className="settings-label">Provider Type</label>
                <select
                  className="argus-select"
                  value={newProviderType}
                  onChange={(e) => setNewProviderType(e.target.value)}
                >
                  <option value="openai_compat">OpenAI Compatible (OpenRouter, LM Studio)</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="google">Google Gemini</option>
                </select>
              </div>

              <div className="settings-field">
                <label className="settings-label">Display Name</label>
                <input
                  className="argus-input"
                  value={newProviderName}
                  onChange={(e) => setNewProviderName(e.target.value)}
                  placeholder="e.g. OpenRouter"
                />
              </div>

              <div className="settings-field settings-field--full">
                <label className="settings-label">API Key</label>
                <input
                  className="argus-input"
                  type="password"
                  value={newApiKey}
                  onChange={(e) => setNewApiKey(e.target.value)}
                  placeholder="sk-…"
                />
              </div>

              {newProviderType === 'openai_compat' && (
                <div className="settings-field settings-field--full">
                  <label className="settings-label">Base URL <span className="settings-optional">(optional)</span></label>
                  <input
                    className="argus-input"
                    value={newBaseUrl}
                    onChange={(e) => setNewBaseUrl(e.target.value)}
                    placeholder="e.g. https://openrouter.ai/api/v1"
                  />
                </div>
              )}
            </div>

            <div className="add-provider-actions">
              <button
                className="settings-add-btn"
                onClick={handleAddProvider}
                disabled={!newProviderName || !newApiKey}
              >
                Add Provider
              </button>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};
