/** Character detail — voice editor with presets, casting, and voice library. */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiJson } from '../api/client';
import { AudioPlayer } from '../components/AudioPlayer';
import { ConnectionStatus } from '../components/ConnectionStatus';
import { useBackend, backendReady } from '../context/BackendContext';
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
  is_builtin: boolean;
}

interface ModePresetData {
  name: string;
  type: 'mode';
  instruct: string;
  ref_text: string;
  tags: string[];
  is_builtin: boolean;
}

type PresetEntry = EmotionPresetData | ModePresetData;

interface PresetsResponse {
  emotions: EmotionPresetData[];
  modes: ModePresetData[];
}

interface PresetRow {
  key: string;
  name: string;
  type: 'emotion' | 'mode';
  intensity: string;
  instruct: string;
  text: string;
  original: PresetEntry;
  is_builtin: boolean;
}

/* ── Add-preset form state ───────────────────────────────────── */

interface AddPresetForm {
  type: 'emotion' | 'mode';
  name: string;
  instruct_medium: string;
  instruct_intense: string;
  ref_text_medium: string;
  ref_text_intense: string;
  instruct: string;
  ref_text: string;
  tags: string;
}

/* ── Quick feedback buttons for LLM refinement ───────────────── */

const QUICK_FEEDBACK = [
  'Too nasal',
  'Not enough emotion',
  'Too much emotion',
  'Pitch too high',
  'Pitch too low',
  'Too breathy',
  'Sounds robotic',
  'Wrong accent',
  'Too fast',
  'Too slow',
  'Needs more warmth',
  'Too aggressive',
];

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
      is_builtin: e.is_builtin,
    });
    rows.push({
      key: `${e.name}_intense`,
      name: e.name,
      type: 'emotion',
      intensity: 'intense',
      instruct: e.instruct_intense,
      text: e.ref_text_intense,
      original: e,
      is_builtin: e.is_builtin,
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
      is_builtin: m.is_builtin,
    });
  }
  return rows;
}

/* ── Component ──────────────────────────────────────────────────── */

export function CharacterPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  // GPU backend availability — read from shared BackendContext (populated by ConnectionStatus)
  const { status: backendStatus } = useBackend();
  const gpuAvailable = backendReady(backendStatus);
  const noGpuTooltip = 'No GPU backend available — connect tunnel or wait for RunPod';

  const [character, setCharacter] = useState<Character | null>(null);
  const [baseDesc, setBaseDesc] = useState('');
  const [savingDesc, setSavingDesc] = useState(false);
  const [presets, setPresets] = useState<PresetRow[]>([]);
  const [prompts, setPrompts] = useState<VoicePrompt[]>([]);
  const [preview, setPreview] = useState<{ audio: string; format: string; label: string } | null>(null);
  const [generating, setGenerating] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [tab, setTab] = useState<'presets' | 'library'>('presets');
  const [filter, setFilter] = useState<'all' | 'emotions' | 'modes'>('all');
  const [refineKey, setRefineKey] = useState<string | null>(null);
  const [feedback, setFeedback] = useState('');
  const [refining, setRefining] = useState(false);
  const [refineResult, setRefineResult] = useState<RefineResult | null>(null);
  const [castingAll, setCastingAll] = useState(false);
  const [castProgress, setCastProgress] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [showTechnical, setShowTechnical] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [savingPreset, setSavingPreset] = useState<string | null>(null);
  const [deletingPreset, setDeletingPreset] = useState<string | null>(null);
  const [addForm, setAddForm] = useState<AddPresetForm>({
    type: 'emotion',
    name: '',
    instruct_medium: '',
    instruct_intense: '',
    ref_text_medium: '',
    ref_text_intense: '',
    instruct: '',
    ref_text: '',
    tags: '',
  });
  const [addingPreset, setAddingPreset] = useState(false);

  // ── Cold-start / generation progress state ──────────────────
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [retryTarget, setRetryTarget] = useState<{ row: PresetRow; op: 'preview' | 'cast' } | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortCtrlRef = useRef<AbortController | null>(null);
  /** True when the 180s hard timeout fired (vs. user-initiated cancel). */
  const wasTimedOutRef = useRef(false);

  /* ── Load data ─────────────────────────────────────────────── */

  useEffect(() => {
    if (!id) return;
    apiJson<Character>(`/api/v1/characters/${id}`)
      .then(c => { setCharacter(c); setBaseDesc(c.base_description); })
      .catch(() => navigate('/'));
  }, [id]);

  useEffect(() => {
    apiJson<PresetsResponse>('/api/v1/presets')
      .then(data => setPresets(flattenPresets(data)))
      .catch(() => {});
  }, []);

  const loadPrompts = useCallback(() => {
    if (!character) return;
    apiJson<{ prompts: VoicePrompt[] }>(
      `/api/v1/tts/voices/prompts/search?character=${character.name.toLowerCase()}`
    ).then(d => setPrompts(d.prompts || [])).catch(() => {});
  }, [character]);

  useEffect(() => { loadPrompts(); }, [loadPrompts]);

  /* ── Error display helper ──────────────────────────────────── */

  const handleError = (e: unknown, context: string) => {
    const msg = (e as Error).message;
    let detail = msg;
    if (msg.includes('502') || msg.includes('503')) {
      detail = `${context}: GPU backend unreachable. Check connection status on dashboard.`;
    } else if (msg.includes('504') || msg.includes('timeout')) {
      detail = `${context}: Request timed out. The GPU may be cold-starting (~30s).`;
    } else {
      detail = `${context}: ${msg}`;
    }
    setError(detail);
    setTimeout(() => setError(null), 10000);
  };

  /* ── Generation lifecycle helpers ─────────────────────────── */

  /** Start a tracked generation. Returns an AbortController whose signal to pass to fetch. */
  const startGeneration = useCallback((key: string): AbortController => {
    const ctrl = new AbortController();
    abortCtrlRef.current = ctrl;
    wasTimedOutRef.current = false;
    setGenerating(key);
    setElapsedSeconds(0);
    setRetryTarget(null);
    setError(null);

    // Tick elapsed counter every second
    timerRef.current = setInterval(() => {
      setElapsedSeconds(s => s + 1);
    }, 1000);

    // Hard timeout at 180s — mark as timeout before aborting so catch block can distinguish
    timeoutRef.current = setTimeout(() => {
      wasTimedOutRef.current = true;
      ctrl.abort();
    }, 180_000);

    return ctrl;
  }, []);

  /** Stop a tracked generation (call in finally block). */
  const stopGeneration = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    if (timeoutRef.current) { clearTimeout(timeoutRef.current); timeoutRef.current = null; }
    abortCtrlRef.current = null;
    setGenerating(null);
  }, []);

  /** Cancel the in-flight generation request. */
  const cancelGeneration = useCallback(() => {
    abortCtrlRef.current?.abort();
    stopGeneration();
  }, [stopGeneration]);

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
      handleError(e, 'Save description');
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
    setPreview(null);
    const ctrl = startGeneration(row.key);
    try {
      const fullInstruct = `${baseDesc}, ${row.instruct}`;
      const result = await apiJson<DesignResult>('/api/v1/tts/voices/design', {
        method: 'POST',
        body: JSON.stringify({ text: row.text, instruct: fullInstruct, format: 'wav' }),
        signal: ctrl.signal,
      });
      setPreview({ audio: result.audio, format: 'wav', label: `${row.name} (${row.intensity})` });
    } catch (e) {
      if ((e as Error).name === 'AbortError') {
        if (wasTimedOutRef.current) {
          // Hard 180s timeout fired
          setError(`Preview timed out after 3 minutes. GPU may still be starting — try again.`);
          setRetryTarget({ row, op: 'preview' });
        }
        // User-initiated cancel — stay silent
      } else {
        handleError(e, `Preview "${row.name} ${row.intensity}"`);
      }
    } finally {
      stopGeneration();
    }
  };

  const castSingle = async (row: PresetRow) => {
    if (!character) return;
    const ctrl = startGeneration(row.key + '_cast');
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
        signal: ctrl.signal,
      });
      setPreview({ audio: result.audio, format: 'wav', label: `${row.name} (${row.intensity}) — saved as clone prompt` });
      loadPrompts();
    } catch (e) {
      if ((e as Error).name === 'AbortError') {
        if (wasTimedOutRef.current) {
          setError(`Cast timed out after 3 minutes. GPU may still be starting — try again.`);
          setRetryTarget({ row, op: 'cast' });
        }
        // User-initiated cancel — stay silent
      } else {
        handleError(e, `Cast "${row.name} ${row.intensity}"`);
      }
    } finally {
      stopGeneration();
    }
  };

  const castAll = async () => {
    if (!character) return;
    setCastingAll(true);
    setError(null);
    setCastProgress('Building batch...');
    try {
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

      setCastProgress(`Casting ${items.length} variants... (this may take several minutes)`);
      await apiJson('/api/v1/tts/voices/cast', {
        method: 'POST',
        body: JSON.stringify({
          character: character.name.toLowerCase(),
          description: baseDesc,
          entries: items,
          format: 'wav',
        }),
      });
      setCastProgress('Done!');
      loadPrompts();
    } catch (e) {
      handleError(e, 'Cast All');
    } finally {
      setCastingAll(false);
      setTimeout(() => setCastProgress(''), 3000);
    }
  };

  const refinePreset = async (row: PresetRow, feedbackText?: string) => {
    const fb = feedbackText || feedback;
    if (!fb.trim()) return;
    setRefining(true);
    setError(null);
    try {
      const result = await apiJson<RefineResult>('/api/v1/tts/voices/refine', {
        method: 'POST',
        body: JSON.stringify({
          current_instruct: `${baseDesc}, ${row.instruct}`,
          base_description: baseDesc,
          ref_text: row.text,
          feedback: fb,
        }),
      });
      setRefineResult(result);
      const newInstruct = result.new_instruct.startsWith(baseDesc)
        ? result.new_instruct.slice(baseDesc.length).replace(/^,\s*/, '')
        : result.new_instruct;
      updatePreset(row.key, 'instruct', newInstruct);
    } catch (e) {
      handleError(e, 'LLM Refinement');
    } finally {
      setRefining(false);
    }
  };

  const savePreset = async (row: PresetRow) => {
    setSavingPreset(row.key);
    setError(null);
    try {
      if (row.type === 'emotion') {
        // For emotion, we need both intensities. Find the sibling row.
        const siblingIntensity = row.intensity === 'medium' ? 'intense' : 'medium';
        const siblingKey = `${row.name}_${siblingIntensity}`;
        const sibling = presets.find(p => p.key === siblingKey);
        const body: Record<string, string> = {};
        if (row.intensity === 'medium') {
          body.instruct_medium = row.instruct;
          body.ref_text_medium = row.text;
          if (sibling) { body.instruct_intense = sibling.instruct; body.ref_text_intense = sibling.text; }
        } else {
          body.instruct_intense = row.instruct;
          body.ref_text_intense = row.text;
          if (sibling) { body.instruct_medium = sibling.instruct; body.ref_text_medium = sibling.text; }
        }
        await apiJson(`/api/v1/presets/emotions/${row.name}`, {
          method: 'PATCH',
          body: JSON.stringify(body),
        });
      } else {
        await apiJson(`/api/v1/presets/modes/${row.name}`, {
          method: 'PATCH',
          body: JSON.stringify({ instruct: row.instruct, ref_text: row.text }),
        });
      }
      // Refresh presets from server so is_builtin flags update
      const data = await apiJson<PresetsResponse>('/api/v1/presets');
      setPresets(flattenPresets(data));
    } catch (e) {
      handleError(e, `Save "${row.name}"`);
    } finally {
      setSavingPreset(null);
    }
  };

  const deletePreset = async (row: PresetRow) => {
    if (!confirm(`Delete custom preset "${row.name}"? This cannot be undone.`)) return;
    setDeletingPreset(row.name);
    setError(null);
    try {
      const endpoint = row.type === 'emotion'
        ? `/api/v1/presets/emotions/${row.name}`
        : `/api/v1/presets/modes/${row.name}`;
      await apiJson(endpoint, { method: 'DELETE' });
      const data = await apiJson<PresetsResponse>('/api/v1/presets');
      setPresets(flattenPresets(data));
    } catch (e) {
      handleError(e, `Delete "${row.name}"`);
    } finally {
      setDeletingPreset(null);
    }
  };

  const createPreset = async () => {
    if (!addForm.name.trim()) return;
    setAddingPreset(true);
    setError(null);
    try {
      const tags = addForm.tags.split(',').map(t => t.trim()).filter(Boolean);
      if (addForm.type === 'emotion') {
        await apiJson('/api/v1/presets/emotions', {
          method: 'POST',
          body: JSON.stringify({
            name: addForm.name.trim(),
            instruct_medium: addForm.instruct_medium,
            instruct_intense: addForm.instruct_intense,
            ref_text_medium: addForm.ref_text_medium,
            ref_text_intense: addForm.ref_text_intense,
            tags,
          }),
        });
      } else {
        await apiJson('/api/v1/presets/modes', {
          method: 'POST',
          body: JSON.stringify({
            name: addForm.name.trim(),
            instruct: addForm.instruct,
            ref_text: addForm.ref_text,
            tags,
          }),
        });
      }
      const data = await apiJson<PresetsResponse>('/api/v1/presets');
      setPresets(flattenPresets(data));
      setShowAddModal(false);
      setAddForm({
        type: 'emotion', name: '', instruct_medium: '', instruct_intense: '',
        ref_text_medium: '', ref_text_intense: '', instruct: '', ref_text: '', tags: '',
      });
    } catch (e) {
      handleError(e, 'Create preset');
    } finally {
      setAddingPreset(false);
    }
  };

  const playPrompt = async (promptName: string) => {
    setGenerating(promptName);
    setPreview(null);
    setError(null);
    try {
      const result = await apiJson<DesignResult>('/api/v1/tts/synthesize', {
        method: 'POST',
        body: JSON.stringify({ voice_prompt: promptName, text: 'Hello, this is a test of my voice.', format: 'wav' }),
      });
      setPreview({ audio: result.audio, format: 'wav', label: promptName });
    } catch (e) {
      handleError(e, `Play "${promptName}"`);
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
      handleError(e, 'Delete prompt');
    }
  };

  /* ── Render ────────────────────────────────────────────────── */

  if (!character) return <div className="loading">Loading...</div>;

  const filteredPresets = presets.filter(p => {
    if (filter === 'emotions') return p.type === 'emotion';
    if (filter === 'modes') return p.type === 'mode';
    return true;
  });

  const promptGroups = new Map<string, VoicePrompt[]>();
  for (const p of prompts) {
    const key = p.emotion || 'other';
    if (!promptGroups.has(key)) promptGroups.set(key, []);
    promptGroups.get(key)!.push(p);
  }

  const existingPromptKeys = new Set(prompts.map(p => {
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

      {/* Connection Status */}
      <ConnectionStatus />

      {/* Error banner */}
      {error && (
        <div className="flash error">
          <span>⚠️ {error}</span>
          <div className="flash-actions">
            {retryTarget && (
              <button
                className="btn-sm btn-retry"
                onClick={() => {
                  const { row, op } = retryTarget;
                  setRetryTarget(null);
                  setError(null);
                  if (op === 'preview') previewPreset(row);
                  else castSingle(row);
                }}
              >
                ↩ Retry
              </button>
            )}
            <button className="btn-sm btn-dismiss" onClick={() => { setError(null); setRetryTarget(null); }}>✕</button>
          </div>
        </div>
      )}

      {/* Base Description */}
      <section className="base-section">
        <h3>Base Voice Description</h3>
        <p className="hint">Physical traits only — pitch, texture, resonance, accent. No mood/emotion words.</p>
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

      {/* Technical info toggle */}
      <div className="technical-toggle">
        <button onClick={() => setShowTechnical(!showTechnical)} className="btn-link" style={{ fontSize: 12 }}>
          {showTechnical ? '🔧 Hide technical details' : '🔧 Show technical details'}
        </button>
      </div>

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
          {/* Explanation */}
          <div className="info-box">
            <strong>What are presets?</strong> Presets define how a character expresses emotions (joy, anger, fear...)
            and delivery modes (whispering, shouting, laughing...). Each preset has an instruction for the TTS model
            and sample text. You can preview how they sound, edit them, then <strong>cast</strong> to save as reusable
            voice prompts.
          </div>

          {showTechnical && (
            <div className="info-box technical">
              <strong>🔧 Technical:</strong> Preview uses <code>VoiceDesign</code> (generates a new voice from text description each time — results vary).
              Casting uses <code>VoiceDesign → create_clone_prompt</code> (generates once, saves as a reusable tensor prompt for consistent reproduction).
            </div>
          )}

          {/* No-GPU warning banner */}
          {!gpuAvailable && backendStatus !== 'checking' && (
            <div className="no-gpu-warning">
              ⚠️ No GPU backend available — Preview and Cast are disabled.
              Connect the GPU tunnel or wait for RunPod to become ready.
            </div>
          )}

          <div className="presets-toolbar">
            <div className="filter-group">
              <button className={`btn-filter ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}>All</button>
              <button className={`btn-filter ${filter === 'emotions' ? 'active' : ''}`} onClick={() => setFilter('emotions')}>
                Emotions ({presets.filter(p => p.type === 'emotion' && p.intensity === 'medium').length})
              </button>
              <button className={`btn-filter ${filter === 'modes' ? 'active' : ''}`} onClick={() => setFilter('modes')}>
                Modes ({presets.filter(p => p.type === 'mode').length})
              </button>
            </div>
            <div className="toolbar-right">
              <button onClick={() => setShowAddModal(true)} className="btn-secondary" title="Create a new custom preset">
                ＋ Add Preset
              </button>
              <button
                onClick={castAll}
                disabled={castingAll || !gpuAvailable}
                className="btn-primary"
                title={!gpuAvailable ? noGpuTooltip : 'Generate and save all emotion/mode variants as clone prompts'}
              >
                {castingAll ? castProgress : '🎭 Cast All Presets'}
              </button>
            </div>
          </div>

          <div className="preset-list">
            {filteredPresets.map(row => {
              const isExpanded = expanded === row.key;
              const isGenerating = generating === row.key || generating === row.key + '_cast';
              const hasPrompt = existingPromptKeys.has(row.key);
              const isRefining = refineKey === row.key;

              return (
                <div key={row.key} className={`preset-row ${isExpanded ? 'expanded' : ''} ${hasPrompt ? 'has-prompt' : ''} ${!row.is_builtin ? 'custom-preset' : ''} ${isGenerating ? 'generating' : ''}`}>
                  {/* Compact header */}
                  <div className="preset-header" onClick={() => setExpanded(isExpanded ? null : row.key)}>
                    <div className="preset-label">
                      <span className={`preset-type ${row.type}`}>{row.type === 'emotion' ? '😊' : '🎤'}</span>
                      <strong>{row.name}</strong>
                      <span className={`badge intensity-${row.intensity}`}>{row.intensity}</span>
                      {hasPrompt && <span className="badge cast" title="Already cast — clone prompt saved">✓ cast</span>}
                      {!row.is_builtin && <span className="badge custom" title="Custom preset — editable and deletable">✎ custom</span>}
                    </div>
                    <div className="preset-summary">{row.instruct.slice(0, 60)}{row.instruct.length > 60 ? '...' : ''}</div>
                    <div className="preset-actions-compact">
                      <button
                        onClick={e => { e.stopPropagation(); previewPreset(row); }}
                        disabled={isGenerating || !gpuAvailable}
                        className="btn-sm"
                        title={!gpuAvailable ? noGpuTooltip : 'Preview — generate a one-off sample (VoiceDesign, not saved)'}
                      >
                        {isGenerating && generating === row.key ? '⏳' : '▶ Preview'}
                      </button>
                      <button
                        onClick={e => { e.stopPropagation(); castSingle(row); }}
                        disabled={isGenerating || !gpuAvailable}
                        className="btn-sm btn-cast"
                        title={!gpuAvailable ? noGpuTooltip : 'Cast — generate and save as reusable clone prompt'}
                      >
                        {isGenerating && generating === row.key + '_cast' ? '⏳' : '💾 Cast'}
                      </button>
                      {!row.is_builtin && row.intensity !== 'intense' && (
                        <button
                          onClick={e => { e.stopPropagation(); deletePreset(row); }}
                          disabled={deletingPreset === row.name}
                          className="btn-sm btn-danger"
                          title="Delete this custom preset"
                        >
                          {deletingPreset === row.name ? '⏳' : '🗑'}
                        </button>
                      )}
                      <span className="expand-icon">{isExpanded ? '▼' : '▶'}</span>
                    </div>
                  </div>

                  {/* Generating status bar */}
                  {isGenerating && (
                    <div className="generating-status">
                      <div className="generating-timer">
                        <span className="spinner-dot" />
                        Generating... ({elapsedSeconds}s)
                        {elapsedSeconds > 15 && (
                          <span className="cold-start-msg"> — GPU starting up, this may take up to 2 minutes…</span>
                        )}
                      </div>
                      <button
                        className="btn-sm btn-cancel"
                        onClick={e => { e.stopPropagation(); cancelGeneration(); }}
                        title="Cancel request"
                      >
                        ✕ Cancel
                      </button>
                    </div>
                  )}

                  {/* Expanded editor */}
                  {isExpanded && (
                    <div className="preset-editor">
                      <div className="editor-field">
                        <label>Instruct <span className="hint">(emotion/delivery direction — prepended with base description)</span></label>
                        <textarea
                          value={row.instruct}
                          onChange={e => updatePreset(row.key, 'instruct', e.target.value)}
                          rows={3}
                        />
                      </div>
                      <div className="editor-field">
                        <label>Sample Text <span className="hint">(what to say in the casting clip)</span></label>
                        <textarea
                          value={row.text}
                          onChange={e => updatePreset(row.key, 'text', e.target.value)}
                          rows={3}
                        />
                      </div>

                      {showTechnical && (
                        <div className="editor-field">
                          <label className="hint">Full instruct sent to VoiceDesign model:</label>
                          <code className="full-instruct">{baseDesc}, {row.instruct}</code>
                        </div>
                      )}

                      <div className="editor-actions">
                        <button
                          onClick={() => previewPreset(row)}
                          disabled={!!generating || !gpuAvailable}
                          className="btn-primary btn-sm"
                          title={!gpuAvailable ? noGpuTooltip : undefined}
                        >
                          {generating === row.key ? '⏳ Generating...' : '🔊 Preview'}
                        </button>
                        <button
                          onClick={() => castSingle(row)}
                          disabled={!!generating || !gpuAvailable}
                          className="btn-secondary btn-sm"
                          title={!gpuAvailable ? noGpuTooltip : undefined}
                        >
                          💾 Cast & Save
                        </button>
                        <button
                          onClick={() => savePreset(row)}
                          disabled={savingPreset === row.key}
                          className="btn-sm"
                          title={row.is_builtin ? 'Save as custom override (built-in stays intact)' : 'Save changes to server'}
                        >
                          {savingPreset === row.key ? '⏳ Saving...' : row.is_builtin ? '✎ Override & Save' : '✎ Save Changes'}
                        </button>
                        <button onClick={() => resetPreset(row.key)} className="btn-sm">↩ Reset</button>
                        <button
                          onClick={() => { setRefineKey(isRefining ? null : row.key); setRefineResult(null); setFeedback(''); }}
                          className="btn-sm"
                        >
                          {isRefining ? '✕ Close' : '✨ Refine with AI'}
                        </button>
                      </div>

                      {/* LLM Refine inline */}
                      {isRefining && (
                        <div className="refine-inline">
                          <p className="hint" style={{ marginBottom: 8 }}>Quick feedback — click a button or type your own:</p>
                          <div className="quick-feedback-grid">
                            {QUICK_FEEDBACK.map(fb => (
                              <button
                                key={fb}
                                onClick={() => refinePreset(row, fb)}
                                disabled={refining}
                                className="btn-sm btn-quick-feedback"
                              >
                                {fb}
                              </button>
                            ))}
                          </div>
                          <textarea
                            placeholder="Or describe what's wrong in your own words..."
                            value={feedback}
                            onChange={e => setFeedback(e.target.value)}
                            rows={2}
                          />
                          <button onClick={() => refinePreset(row)} disabled={refining || !feedback.trim()} className="btn-primary btn-sm">
                            {refining ? '🤔 Thinking...' : '✨ Refine'}
                          </button>
                          {refineResult && (
                            <div className="refine-result">
                              <p><strong>Changes:</strong> {refineResult.explanation}</p>
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

      {/* ── Add Preset Modal ─────────────────────────────────── */}
      {showAddModal && (
        <div className="modal-overlay" onClick={() => setShowAddModal(false)}>
          <div className="modal-card" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Add Custom Preset</h3>
              <button className="btn-link" onClick={() => setShowAddModal(false)}>✕</button>
            </div>

            <div className="form-row">
              <label>Type</label>
              <select
                value={addForm.type}
                onChange={e => setAddForm(f => ({ ...f, type: e.target.value as 'emotion' | 'mode' }))}
              >
                <option value="emotion">Emotion (medium + intense variants)</option>
                <option value="mode">Mode (single variant)</option>
              </select>
            </div>

            <div className="form-row">
              <label>Name <span className="hint">(unique, lowercase recommended)</span></label>
              <input
                type="text"
                placeholder="e.g. nostalgic"
                value={addForm.name}
                onChange={e => setAddForm(f => ({ ...f, name: e.target.value }))}
              />
            </div>

            {addForm.type === 'emotion' ? (
              <>
                <div className="form-row">
                  <label>Instruct — Medium</label>
                  <textarea
                    rows={2}
                    placeholder="e.g. gently nostalgic, warmly remembering the past"
                    value={addForm.instruct_medium}
                    onChange={e => setAddForm(f => ({ ...f, instruct_medium: e.target.value }))}
                  />
                </div>
                <div className="form-row">
                  <label>Sample Text — Medium</label>
                  <textarea
                    rows={2}
                    placeholder="e.g. I remember when we used to come here every summer."
                    value={addForm.ref_text_medium}
                    onChange={e => setAddForm(f => ({ ...f, ref_text_medium: e.target.value }))}
                  />
                </div>
                <div className="form-row">
                  <label>Instruct — Intense</label>
                  <textarea
                    rows={2}
                    placeholder="e.g. overwhelmed with nostalgia, voice cracking with memory"
                    value={addForm.instruct_intense}
                    onChange={e => setAddForm(f => ({ ...f, instruct_intense: e.target.value }))}
                  />
                </div>
                <div className="form-row">
                  <label>Sample Text — Intense</label>
                  <textarea
                    rows={2}
                    placeholder="e.g. This place hasn't changed at all. I can still see us, kids again, running through these halls."
                    value={addForm.ref_text_intense}
                    onChange={e => setAddForm(f => ({ ...f, ref_text_intense: e.target.value }))}
                  />
                </div>
              </>
            ) : (
              <>
                <div className="form-row">
                  <label>Instruct</label>
                  <textarea
                    rows={2}
                    placeholder="e.g. conspiratorial, hushed and urgent"
                    value={addForm.instruct}
                    onChange={e => setAddForm(f => ({ ...f, instruct: e.target.value }))}
                  />
                </div>
                <div className="form-row">
                  <label>Sample Text</label>
                  <textarea
                    rows={2}
                    placeholder="e.g. Don't tell anyone, but I know what really happened."
                    value={addForm.ref_text}
                    onChange={e => setAddForm(f => ({ ...f, ref_text: e.target.value }))}
                  />
                </div>
              </>
            )}

            <div className="form-row">
              <label>Tags <span className="hint">(comma-separated, optional)</span></label>
              <input
                type="text"
                placeholder="e.g. nostalgic, memories"
                value={addForm.tags}
                onChange={e => setAddForm(f => ({ ...f, tags: e.target.value }))}
              />
            </div>

            <div className="modal-actions">
              <button onClick={() => setShowAddModal(false)} className="btn-secondary">Cancel</button>
              <button
                onClick={createPreset}
                disabled={addingPreset || !addForm.name.trim()}
                className="btn-primary"
              >
                {addingPreset ? 'Creating...' : 'Create Preset'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Voice Library Tab ────────────────────────────────── */}
      {tab === 'library' && (
        <section className="library-tab">
          <div className="info-box">
            <strong>Voice Library</strong> contains saved clone prompts — reusable voice snapshots that produce
            consistent output every time. Use these for production rendering.
          </div>

          {showTechnical && (
            <div className="info-box technical">
              <strong>🔧 Technical:</strong> Play uses <code>synthesize_with_clone_prompt</code> (consistent voice from saved tensor prompt).
              Delete removes the <code>.pt</code> file from the GPU server.
            </div>
          )}

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
                          disabled={generating === p.name || !gpuAvailable}
                          className="btn-sm"
                          title={!gpuAvailable ? noGpuTooltip : 'Synthesize test text using this clone prompt'}
                        >
                          {generating === p.name ? '⏳' : '▶ Play'}
                        </button>
                        <button onClick={() => deletePrompt(p.name)} className="btn-sm btn-danger" title="Delete this clone prompt">
                          🗑
                        </button>
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
