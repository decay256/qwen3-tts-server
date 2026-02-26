/** Dashboard — list characters, create new, show TTS status. */

import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { apiJson } from '../api/client';
import type { Character, TTSStatus } from '../api/types';

export function DashboardPage() {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [status, setStatus] = useState<TTSStatus | null>(null);
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  useEffect(() => {
    apiJson<Character[]>('/api/v1/characters').then(setCharacters).catch(() => {});
    apiJson<TTSStatus>('/api/v1/tts/status').then(setStatus).catch(() => {});
  }, []);

  const createCharacter = async () => {
    if (!name.trim() || !desc.trim()) return;
    setCreating(true);
    try {
      const char = await apiJson<Character>('/api/v1/characters', {
        method: 'POST',
        body: JSON.stringify({ name, base_description: desc }),
      });
      setCharacters(prev => [...prev, char]);
      setName('');
      setDesc('');
      setShowForm(false);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="dashboard">
      <div className="status-bar">
        <h2>Voice Studio</h2>
        {status && (
          <div className="status-info">
            <span className={`dot ${status.tunnel_connected ? 'green' : 'red'}`} />
            GPU {status.tunnel_connected ? 'Connected' : 'Disconnected'}
            {status.tunnel_connected && ` · ${status.models_loaded.join(', ')} · ${status.prompts_count} prompts`}
          </div>
        )}
      </div>

      <section className="characters-section">
        <div className="section-header">
          <h3>Characters ({characters.length})</h3>
          <button onClick={() => setShowForm(!showForm)} className="btn-primary">
            {showForm ? 'Cancel' : '+ New Character'}
          </button>
        </div>

        {showForm && (
          <div className="create-form">
            <input
              placeholder="Character name (e.g., Kira)"
              value={name}
              onChange={e => setName(e.target.value)}
            />
            <textarea
              placeholder="Base voice description — physical traits only (e.g., Adult woman, low-mid pitch, husky voice, slight rasp, American accent)"
              value={desc}
              onChange={e => setDesc(e.target.value)}
              rows={3}
            />
            <button onClick={createCharacter} disabled={creating} className="btn-primary">
              {creating ? 'Creating...' : 'Create'}
            </button>
          </div>
        )}

        <div className="character-grid">
          {characters.map(char => (
            <Link key={char.id} to={`/characters/${char.id}`} className="character-card">
              <h4>{char.name}</h4>
              <p className="desc">{char.base_description}</p>
            </Link>
          ))}
          {characters.length === 0 && !showForm && (
            <p className="empty">No characters yet. Create one to get started.</p>
          )}
        </div>
      </section>
    </div>
  );
}
