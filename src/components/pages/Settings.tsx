import React, { useState } from 'react';
import { useSettingsStore } from '@/stores/settingsStore';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { Card } from '../ui/Card';
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
    <div className="settings-page p-8 max-w-4xl mx-auto w-full animation-fade-in">
      <h1 className="text-2xl font-bold text-primary mb-6">⚙️ Settings</h1>
      
      <div className="grid gap-8">
        <Card className="p-6">
          <h2 className="text-xl font-semibold text-primary mb-4 border-b border-border-subtle pb-2">API Providers</h2>
          <p className="text-sm text-secondary mb-6">
            Add your API keys to power the agents. Keys are stored locally in your browser/app storage.
          </p>
          
          {/* Provider List */}
          <div className="space-y-4 mb-8">
            {providers.length === 0 ? (
              <div className="text-center p-4 bg-white/5 rounded border border-border-subtle text-muted text-sm">
                No providers added yet.
              </div>
            ) : (
              providers.map(p => (
                <div key={p.id} className="flex items-center justify-between p-4 glass-surface rounded-lg border border-border-medium">
                  <div>
                    <div className="font-semibold text-primary">{p.name} <span className="text-xs text-muted uppercase ml-2 bg-white/10 px-2 py-0.5 rounded">{p.type}</span></div>
                    {p.baseUrl && <div className="text-xs text-muted mt-1">{p.baseUrl}</div>}
                  </div>
                  <Button variant="ghost" className="text-red-400" onClick={() => removeProvider(p.id)}>Remove</Button>
                </div>
              ))
            )}
          </div>
          
          {/* Add New Provider */}
          <div className="bg-black/20 p-4 rounded-lg border border-border-strong">
            <h3 className="font-semibold text-sm mb-4">Add New Provider</h3>
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-xs text-muted mb-1">Provider Type</label>
                <select 
                  className="w-full glass-surface border border-border-strong rounded p-2 text-sm text-primary"
                  value={newProviderType}
                  onChange={(e) => setNewProviderType(e.target.value)}
                >
                  <option value="openai_compat">OpenAI Compatible (OpenRouter, LM Studio)</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="google">Google Gemini</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">Display Name</label>
                <Input 
                  value={newProviderName} 
                  onChange={(e) => setNewProviderName(e.target.value)} 
                  placeholder="e.g. OpenRouter" 
                />
              </div>
              <div className="col-span-2">
                <label className="block text-xs text-muted mb-1">API Key</label>
                <Input 
                  type="password" 
                  value={newApiKey} 
                  onChange={(e) => setNewApiKey(e.target.value)} 
                  placeholder="sk-..." 
                />
              </div>
              {newProviderType === 'openai_compat' && (
                <div className="col-span-2">
                  <label className="block text-xs text-muted mb-1">Base URL (Optional)</label>
                  <Input 
                    value={newBaseUrl} 
                    onChange={(e) => setNewBaseUrl(e.target.value)} 
                    placeholder="e.g. https://openrouter.ai/api/v1" 
                  />
                </div>
              )}
            </div>
            <div className="flex justify-end">
              <Button variant="primary" onClick={handleAddProvider} disabled={!newProviderName || !newApiKey}>
                Add Provider
              </Button>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
};
