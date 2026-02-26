/** Configuration page — view and update LLM/TTS settings. */

import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiJson } from '../api/client';

interface Config {
  tts_relay_url: string;
  llm_provider: string;
  llm_model: string;
  email_from: string;
  has_resend_key: boolean;
  has_openai_key: boolean;
  has_anthropic_key: boolean;
}

export function ConfigPage() {
  const navigate = useNavigate();
  const [config, setConfig] = useState<Config | null>(null);
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    apiJson<Config>('/api/v1/config').then(c => {
      setConfig(c);
      setProvider(c.llm_provider);
      setModel(c.llm_model);
    }).catch(() => {});
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const c = await apiJson<Config>('/api/v1/config', {
        method: 'PATCH',
        body: JSON.stringify({ llm_provider: provider, llm_model: model }),
      });
      setConfig(c);
      setMsg('Configuration saved');
      setTimeout(() => setMsg(null), 3000);
    } catch (e: any) {
      setMsg(`Error: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  if (!config) return <div className="loading">Loading...</div>;

  const suggestedModels = provider === 'anthropic'
    ? ['claude-sonnet-4-6', 'claude-opus-4-6', 'claude-haiku-4-5']
    : ['gpt-4o-mini', 'gpt-4o', 'gpt-5-mini', 'gpt-5'];

  return (
    <div className="config-page">
      <button onClick={() => navigate('/')} className="btn-back">← Back</button>
      <h2>Configuration</h2>

      {msg && <div className="flash success">{msg}</div>}

      <section>
        <h3>TTS Relay</h3>
        <div className="info-row"><span>URL:</span> <code>{config.tts_relay_url}</code></div>
        <p className="hint">Change in .env file on the server.</p>
      </section>

      <section>
        <h3>LLM Provider</h3>
        <div className="form-row">
          <label>Provider</label>
          <select value={provider} onChange={e => { setProvider(e.target.value); setModel(e.target.value === 'anthropic' ? 'claude-sonnet-4-20250514' : 'gpt-4o-mini'); }}>
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </div>
        <div className="form-row">
          <label>Model</label>
          <select value={model} onChange={e => setModel(e.target.value)}>
            {suggestedModels.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          <input placeholder="Or type custom model..." value={model} onChange={e => setModel(e.target.value)} />
        </div>
        <button onClick={save} disabled={saving} className="btn-primary">
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
        <p className="hint">Changes are in-memory only — they reset on server restart.</p>
      </section>

      <section>
        <h3>API Keys</h3>
        <div className="info-row">
          <span>OpenAI:</span>
          <span className={config.has_openai_key ? 'text-green' : 'text-red'}>
            {config.has_openai_key ? '✓ Configured' : '✗ Not set'}
          </span>
        </div>
        <div className="info-row">
          <span>Anthropic:</span>
          <span className={config.has_anthropic_key ? 'text-green' : 'text-red'}>
            {config.has_anthropic_key ? '✓ Configured' : '✗ Not set'}
          </span>
        </div>
        <div className="info-row">
          <span>Resend (email):</span>
          <span className={config.has_resend_key ? 'text-green' : 'text-red'}>
            {config.has_resend_key ? '✓ Configured' : '✗ Not set'}
          </span>
        </div>
        <p className="hint">API keys are set in the .env file on the server.</p>
      </section>
    </div>
  );
}
