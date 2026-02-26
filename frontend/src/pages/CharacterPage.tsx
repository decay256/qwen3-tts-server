/** Character detail — voice editor with presets, casting, and voice library. */

import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiJson } from '../api/client';
import { AudioPlayer } from '../components/AudioPlayer';
import type { Character, VoicePrompt, DesignResult, RefineResult } from '../api/types';

/* ── Types ──────────────────────────────────────────────────────── */

interface EmotionPresetData {
  name: string;
  type: 'emotion';
  instruct_medium: string;
  instruct_intense: string;
  ref_text_medium: string;
  ref_text_intense: string;
  tags: string[];
}

interface ModePresetData {
  name: string;
  type: 'mode';
  instruct: string;
  ref_text: string;
  tags: string[];
}

type PresetEntry = EmotionPresetData | ModePresetData;

interface PresetsResponse {
  emotions: EmotionPresetData[];
  modes: ModePresetData[];
}

/* A flattened row for display: one per castable variant */
interface PresetRow {
  key: string;           // e.g. "happy_medium" or "laughing"
  name: string;          // emotion/mode name
  type: 'emotion' | 'mode';
  intensity: string;     // "medium" | "intense" | "full"
  instruct: string;      // editable
  text: string;          // editable
  original: PresetEntry; // for reset
}

/* ── Helpers ─────────────────────────────────────────────────────── */

function flattenPresets(presets: PresetsResponse): PresetRow[] {
  const rows: PresetRow[] = [];
  for (const e of presets.emotions) {
    rows.push({
      key: `${e.name}_medium`,
      name: e.name,
      type: 'emotion',
      intensity: 'medium',
      instruct: e.instruct_medium,
      text: e.ref_text_medium,
      original: e,
    });
    rows.push({
      key: `${e.name}_intense`,
      name: e.name,
      type: 'emotion',
      intensity: 'intense',
      instruct: e.instruct_intense,
      text: e.ref_text_intense,
      original: e,
    });
  }
  for (const m of presets.modes) {
    rows.push({
      key: m.name,
      name: m.name,
      type: 'mode',
      intensity: 'full',
      instruct: m.instruct,
      text: m.ref_text,
      original: m,
    });
  }
  return rows;
}

/* ── Component ──────────────────────────────────────────────────── */

export function CharacterPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  // Character
  const [character, setCharacter] = useState<Character | null>(null);
  const [baseDesc, setBaseDesc] = useState('');
  const [savingDesc, setSavingDesc] = useState(false);

  // Presets
  const [presets, setPresets] = useState<PresetRow[]>([]);
  const [, setPresetsLoaded] = useState(false);

  // Existing prompts (voice library)
  const [prompts, setPrompts] = useState<VoicePrompt[]>([]);

  // Preview
  const [preview, setPreview] = useState<{ audio: string; format: string; label: string } | null>(null);
  const [generating, setGenerating] = useState<string | null>(null); // key of what's generating

  // Expanded preset editor
  const [expanded, setExpanded] = useState<string | null>(null);

  // Tab
  const [tab, setTab] = useState<'presets' | 'library'>('presets');

  // Filter
  const [filter, setFilter] = useState<'all' | 'emotions' | 'modes'>('all');

  // Refine
  const [refineKey, setRefineKey] = useState<string | null>(null);
  const [feedback, setFeedback] = useState('');
  const [refining, setRefining] = useState(false);
  const [refineResult, setRefineResult] = useState<RefineResult | null>(null);

  // Casting
  const [castingAll, setCastingAll] = useState(false);
  const [castProgress, setCastProgress] = useState('');

  /* ── Load data ─────────────────────────────────────────────── */

  useEffect(() => {
    if (!id) return;
    apiJson<Character>(`/api/v1/characters/${id}`)
      .then(c => { setCharacter(c); setBaseDesc(c.base_description); })
      .catch(() => navigate('/'));
  }, [id]);

  useEffect(() => {
    apiJson<PresetsResponse>('/api/v1/presets')
      .then(data => { setPresets(flattenPresets(data)); setPresetsLoaded(true); })
      .catch(() => setPresetsLoaded(true));
  }, []);

  const loadPrompts = useCallback(() => {
    if (!character) return;
    apiJson<{ prompts: VoicePrompt[] }>(
      `/api/v1/tts/voices/prompts/search?character=${character.name.toLowerCase()}`
    ).then(d => setPrompts(d.prompts)).catch(() => {});
  }, [character]);

  useEffect(() => { loadPrompts(); }, [loadPrompts]);

  /* ── Actions ───────────────────────────────────────────────── */

  const saveBaseDescription = async () => {
    if (!character || !baseDesc.trim()) return;
    setSavingDesc(true);
    try {
      const updated = await apiJson<Character>(`/api/v1/characters/${character.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ base_description: baseDesc }),
      });
      setCharacter(updated);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setSavingDesc(false);
    }
  };

  const updatePreset = (key: string, field: 'instruct' | 'text', value: string) => {
    setPresets(prev => prev.map(p => p.key === key ? { ...p, [field]: value } : p));
  };

  const resetPreset = (key: string) => {
    setPresets(prev => prev.map(p => {
      if (p.key !== key) return p;
      const o = p.original;
      if (o.type === 'emotion') {
        const e = o as EmotionPresetData;
        return {
          ...p,
          instruct: p.intensity === 'intense' ? e.instruct_intense : e.instruct_medium,
          text: p.intensity === 'intense' ? e.ref_text_intense : e.ref_text_medium,
        };
      } else {
        const m = o as ModePresetData;
        return { ...p, instruct: m.instruct, text: m.ref_text };
      }
    }));
  };

  const previewPreset = async (row: PresetRow) => {
    if (!character) return;
    setGenerating(row.key);
    setPreview(null);
    try {
      const fullInstruct = `${baseDesc}, ${row.instruct}`;
      const result = await apiJson<DesignResult>('/api/v1/tts/voices/design', {
        method: 'POST',
        body: JSON.stringify({ text: row.text, instruct: fullInstruct, format: 'wav' }),
      });
      setPreview({ audio: result.audio, format: 'wav', label: `${row.name} (${row.intensity})` });
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setGenerating(null);
    }
  };

  const castSingle = async (row: PresetRow) => {
    if (!character) return;
    setGenerating(row.key);
    try {
      const fullInstruct = `${baseDesc}, ${row.instruct}`;
      const promptName = `${character.name.toLowerCase()}_${row.key}`;
      const result = await apiJson<DesignResult>('/api/v1/tts/voices/design', {
        method: 'POST',
        body: JSON.stringify({
          text: row.text,
          instruct: fullInstruct,
          format: 'wav',
          create_prompt: true,
          prompt_name: promptName,
          tags: [row.name, row.intensity, ...(row.type === 'mode' ? ['mode'] : ['emotion'])],
        }),
      });
      setPreview({ audio: result.audio, format: 'wav', label: `${row.name} (${row.intensity}) — saved` });
      loadPrompts();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setGenerating(null);
    }
  };

  const castAll = async () => {
    if (!character) return;
    setCastingAll(true);
    setCastProgress('Building batch...');
    try {
      // Build batch from current (possibly edited) presets
      const items = presets.map(row => ({
        name: `${character.name.toLowerCase()}_${row.key}`,
        text: row.text,
        instruct: `${baseDesc}, ${row.instruct}`,
        language: 'English',
        tags: [row.name, row.intensity, ...(row.type === 'mode' ? ['mode'] : ['emotion'])],
        character: character.name.toLowerCase(),
        emotion: row.name,
        intensity: row.intensity,
        description: `${row.name} (${row.intensity}): ${row.instruct}`,
        base_description: baseDesc,
      }));

      setCastProgress(`Casting ${items.length} variants... (this takes a while)`);
      await apiJson('/api/v1/tts/voices/cast', {
        method: 'POST',
        body: JSON.stringify({
          character: character.name.toLowerCase(),
          description: baseDesc,
          entries: items,
          format: 'wav',
        }),
      });
      setCastProgress('Done! Reloading prompts...');
      loadPrompts();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setCastingAll(false);
      setCastProgress('');
    }
  };

  const refinePreset = async (row: PresetRow) => {
    if (!feedback.trim()) return;
    setRefining(true);
    try {
      const result = await apiJson<RefineResult>('/api/v1/tts/voices/refine', {
        method: 'POST',
        body: JSON.stringify({
          current_instruct: `${baseDesc}, ${row.instruct}`,
          base_description: baseDesc,
          ref_text: row.text,
          feedback,
        }),
      });
      setRefineResult(result);
      // Extract the emotion-specific part (strip base description prefix)
      const newInstruct = result.new_instruct.startsWith(baseDesc)
        ? result.new_instruct.slice(baseDesc.length).replace(/^,\s*/, '')
        : result.new_instruct;
      updatePreset(row.key, 'instruct', newInstruct);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setRefining(false);
    }
  };

  const playPrompt = async (promptName: string) => {
    setGenerating(promptName);
    setPreview(null);
    try {
      const result = await apiJson<DesignResult>('/api/v1/tts/synthesize', {
        method: 'POST',
        body: JSON.stringify({ voice_prompt: promptName, text: 'Hello, this is a test of my voice.', format: 'wav' }),
      });
      setPreview({ audio: result.audio, format: 'wav', label: promptName });
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setGenerating(null);
    }
  };

  const deletePrompt = async (name: string) => {
    if (!confirm(`Delete prompt "${name}"?`)) return;
    try {
      await apiJson(`/api/v1/tts/voices/prompts/${name}`, { method: 'DELETE' });
      setPrompts(prev => prev.filter(p => p.name !== name));
    } catch (e) {
      alert((e as Error).message);
    }
  };

  /* ── Render ────────────────────────────────────────────────── */

  if (!character) return <div className="loading">Loading...</div>;

  const filteredPresets = presets.filter(p => {
    if (filter === 'emotions') return p.type === 'emotion';
    if (filter === 'modes') return p.type === 'mode';
    return true;
  });

  // Group prompts by emotion for library view
  const promptGroups = new Map<string, VoicePrompt[]>();
  for (const p of prompts) {
    const key = p.emotion || 'other';
    if (!promptGroups.has(key)) promptGroups.set(key, []);
    promptGroups.get(key)!.push(p);
  }

  // Which presets have existing prompts?
  const existingPromptKeys = new Set(prompts.map(p => {
    // Extract key from prompt name: "kira_happy_medium" → "happy_medium"
    const prefix = character.name.toLowerCase() + '_';
    return p.name.startsWith(prefix) ? p.name.slice(prefix.length) : p.name;
  }));

  return (
    <div className="character-page">
      {/* Header */}
      <div className="page-header">
        <button onClick={() => navigate('/')} className="btn-back">← Back</button>
        <h2>{character.name}</h2>
      </div>

      {/* Base Description */}
      <section className="base-section">
        <h3>Base Voice Description</h3>
        <p className="hint">Physical traits only — pitch, texture, resonance, accent. No mood words.</p>
        <textarea
          value={baseDesc}
          onChange={e => setBaseDesc(e.target.value)}
          rows={2}
          className="base-desc-input"
        />
        {baseDesc !== character.base_description && (
          <button onClick={saveBaseDescription} disabled={savingDesc} className="btn-primary btn-sm">
            {savingDesc ? 'Saving...' : 'Save Description'}
          </button>
        )}
      </section>

      {/* Audio Preview */}
      {preview && (
        <section className="preview-bar">
          <AudioPlayer audioBase64={preview.audio} format={preview.format} label={preview.label} />
        </section>
      )}

      {/* Tabs */}
      <div className="tab-bar">
        <button className={`tab ${tab === 'presets' ? 'active' : ''}`} onClick={() => setTab('presets')}>
          🎭 Presets ({presets.length})
        </button>
        <button className={`tab ${tab === 'library' ? 'active' : ''}`} onClick={() => setTab('library')}>
          📚 Voice Library ({prompts.length})
        </button>
      </div>

      {/* ── Presets Tab ──────────────────────────────────────── */}
      {tab === 'presets' && (
        <section className="presets-tab">
          <div className="presets-toolbar">
            <div className="filter-group">
              <button className={`btn-filter ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}>All</button>
              <button className={`btn-filter ${filter === 'emotions' ? 'active' : ''}`} onClick={() => setFilter('emotions')}>Emotions (18)</button>
              <button className={`btn-filter ${filter === 'modes' ? 'active' : ''}`} onClick={() => setFilter('modes')}>Modes (13)</button>
            </div>
            <button onClick={castAll} disabled={castingAll} className="btn-primary">
              {castingAll ? castProgress : '🎭 Cast All'}
            </button>
          </div>

          <div className="preset-list">
            {filteredPresets.map(row => {
              const isExpanded = expanded === row.key;
              const isGenerating = generating === row.key;
              const hasPrompt = existingPromptKeys.has(row.key);
              const isRefining = refineKey === row.key;

              return (
                <div key={row.key} className={`preset-row ${isExpanded ? 'expanded' : ''} ${hasPrompt ? 'has-prompt' : ''}`}>
                  {/* Compact header */}
                  <div className="preset-header" onClick={() => setExpanded(isExpanded ? null : row.key)}>
                    <div className="preset-label">
                      <span className={`preset-type ${row.type}`}>{row.type === 'emotion' ? '😊' : '🎤'}</span>
                      <strong>{row.name}</strong>
                      <span className={`badge intensity-${row.intensity}`}>{row.intensity}</span>
                      {hasPrompt && <span className="badge cast">✓ cast</span>}
                    </div>
                    <div className="preset-summary">{row.instruct.slice(0, 80)}{row.instruct.length > 80 ? '...' : ''}</div>
                    <div className="preset-actions-compact">
                      <button
                        onClick={e => { e.stopPropagation(); previewPreset(row); }}
                        disabled={isGenerating}
                        className="btn-sm"
                        title="Preview"
                      >
                        {isGenerating ? '⏳' : '▶'}
                      </button>
                      <button
                        onClick={e => { e.stopPropagation(); castSingle(row); }}
                        disabled={isGenerating}
                        className="btn-sm btn-cast"
                        title="Cast & save as clone prompt"
                      >
                        💾
                      </button>
                      <span className="expand-icon">{isExpanded ? '▼' : '▶'}</span>
                    </div>
                  </div>

                  {/* Expanded editor */}
                  {isExpanded && (
                    <div className="preset-editor">
                      <div className="editor-field">
                        <label>Instruct <span className="hint">(prepended with base description)</span></label>
                        <textarea
                          value={row.instruct}
                          onChange={e => updatePreset(row.key, 'instruct', e.target.value)}
                          rows={3}
                        />
                      </div>
                      <div className="editor-field">
                        <label>Reference Text <span className="hint">(what to say in the casting clip)</span></label>
                        <textarea
                          value={row.text}
                          onChange={e => updatePreset(row.key, 'text', e.target.value)}
                          rows={3}
                        />
                      </div>
                      <div className="editor-field">
                        <label className="hint">Full instruct sent to model:</label>
                        <code className="full-instruct">{baseDesc}, {row.instruct}</code>
                      </div>
                      <div className="editor-actions">
                        <button onClick={() => previewPreset(row)} disabled={!!generating} className="btn-primary btn-sm">
                          {generating === row.key ? '⏳ Generating...' : '🔊 Preview'}
                        </button>
                        <button onClick={() => castSingle(row)} disabled={!!generating} className="btn-secondary btn-sm">
                          💾 Cast & Save
                        </button>
                        <button onClick={() => resetPreset(row.key)} className="btn-sm">↩ Reset</button>
                        <button
                          onClick={() => { setRefineKey(isRefining ? null : row.key); setRefineResult(null); setFeedback(''); }}
                          className="btn-sm"
                        >
                          {isRefining ? '✕ Close' : '✨ Refine with LLM'}
                        </button>
                      </div>

                      {/* LLM Refine inline */}
                      {isRefining && (
                        <div className="refine-inline">
                          <textarea
                            placeholder="What's wrong? (e.g., 'too nasal', 'not angry enough', 'pitch drifts')"
                            value={feedback}
                            onChange={e => setFeedback(e.target.value)}
                            rows={2}
                          />
                          <button onClick={() => refinePreset(row)} disabled={refining} className="btn-primary btn-sm">
                            {refining ? '🤔 Thinking...' : '✨ Refine'}
                          </button>
                          {refineResult && (
                            <div className="refine-result">
                              <p><strong>Explanation:</strong> {refineResult.explanation}</p>
                              <p className="hint">Instruct updated above. Preview to hear the change.</p>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* ── Voice Library Tab ────────────────────────────────── */}
      {tab === 'library' && (
        <section className="library-tab">
          {prompts.length === 0 ? (
            <p className="empty">No clone prompts yet. Use the Presets tab to cast voices.</p>
          ) : (
            Array.from(promptGroups.entries()).map(([emotion, group]) => (
              <div key={emotion} className="emotion-group">
                <h4>{emotion} <span className="count">({group.length})</span></h4>
                <div className="prompt-grid">
                  {group.map(p => (
                    <div key={p.name} className="prompt-card">
                      <div className="prompt-header">
                        <span className="prompt-name">{p.name}</span>
                        {p.intensity && <span className={`badge intensity-${p.intensity}`}>{p.intensity}</span>}
                      </div>
                      {p.description && <p className="prompt-desc">{p.description}</p>}
                      {p.ref_audio_duration_s && <span className="hint">{p.ref_audio_duration_s.toFixed(1)}s</span>}
                      <div className="prompt-actions">
                        <button
                          onClick={() => playPrompt(p.name)}
                          disabled={generating === p.name}
                          className="btn-sm"
                        >
                          {generating === p.name ? '⏳' : '▶ Play'}
                        </button>
                        <button onClick={() => deletePrompt(p.name)} className="btn-sm btn-danger">🗑</button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </section>
      )}
    </div>
  );
}
