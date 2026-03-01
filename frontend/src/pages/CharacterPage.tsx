/** Character detail — voice editor with presets, draft queue, and templates.
 *
 *  Sprint 5 changes:
 *  - Presets are drafting tools: only "📝 Draft" action remains on preset rows.
 *    Preview, Cast & Save, Override & Save, Reset buttons removed.
 *  - Voice Library tab removed (Templates replaces it).
 *  - Drafts auto-load on page open (not just tab switch).
 *  - Poll every 3s while any draft is pending/generating (any tab).
 *  - Retry button on failed drafts (POST /api/v1/drafts/{id}/regenerate).
 *  - ConnectionStatus moved to Layout navbar — removed from this component.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiJson } from '../api/client';
import { api } from '../api/client';
import { AudioPlayer } from '../components/AudioPlayer';
import type { Character, RefineResult, DraftSummary, Draft, TemplateSummary, Template } from '../api/types';

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

  const [character, setCharacter] = useState<Character | null>(null);
  const [baseDesc, setBaseDesc] = useState('');
  const [savingDesc, setSavingDesc] = useState(false);
  const [presets, setPresets] = useState<PresetRow[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  // Sprint 5: 'library' tab removed
  const [tab, setTab] = useState<'presets' | 'drafts' | 'templates'>('presets');

  // ── Draft queue state ──────────────────────────────────────────────────────
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  const [draftsTotal, setDraftsTotal] = useState(0);
  const [draftsLoading, setDraftsLoading] = useState(false);
  const [draftAudio, setDraftAudio] = useState<{ id: string; audio_b64: string; format: string } | null>(null);
  const [draftAudioLoading, setDraftAudioLoading] = useState<string | null>(null);
  const [approvingDraft, setApprovingDraft] = useState<string | null>(null);
  const [discardingDraft, setDiscardingDraft] = useState<string | null>(null);
  const [generatingDraft, setGeneratingDraft] = useState<string | null>(null);
  const [retryingDraft, setRetryingDraft] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Template library state ─────────────────────────────────────────────────
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [templatesTotal, setTemplatesTotal] = useState(0);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [templateAudio, setTemplateAudio] = useState<{ id: string; audio_b64: string; format: string } | null>(null);
  const [templateAudioLoading, setTemplateAudioLoading] = useState<string | null>(null);
  const [deletingTemplate, setDeletingTemplate] = useState<string | null>(null);
  const [renamingTemplate, setRenamingTemplate] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');

  const [filter, setFilter] = useState<'all' | 'emotions' | 'modes'>('all');
  const [refineKey, setRefineKey] = useState<string | null>(null);
  const [feedback, setFeedback] = useState('');
  const [refining, setRefining] = useState(false);
  const [refineResult, setRefineResult] = useState<RefineResult | null>(null);
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

  /* ── Load character + presets ──────────────────────────────── */

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

  /* ── Draft queue ───────────────────────────────────────────── */

  const fetchDrafts = useCallback(async () => {
    if (!id) return;
    try {
      const data = await apiJson<{ drafts: DraftSummary[]; total: number }>(
        `/api/v1/drafts?character_id=${id}&limit=50`
      );
      setDrafts(data.drafts || []);
      setDraftsTotal(data.total ?? 0);
    } catch { /* silently ignore */ }
  }, [id]);

  // Sprint 5: Auto-load drafts on page open (req #4) — load when id is available
  useEffect(() => {
    if (!id) return;
    setDraftsLoading(true);
    fetchDrafts().finally(() => setDraftsLoading(false));
  }, [id, fetchDrafts]);

  // Also reload when switching TO drafts tab
  useEffect(() => {
    if (tab === 'drafts') {
      setDraftsLoading(true);
      fetchDrafts().finally(() => setDraftsLoading(false));
    }
  }, [tab, fetchDrafts]);

  // Sprint 5: Poll every 3s while any draft is pending/generating (req #5)
  // Note: poll runs on ANY tab — not gated to drafts tab only (req #10)
  useEffect(() => {
    const hasActive = drafts.some(d => d.status === 'pending' || d.status === 'generating');
    if (hasActive) {
      pollRef.current = setInterval(fetchDrafts, 3_000);
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [drafts, fetchDrafts]);

  const generateDraft = useCallback(async (row: PresetRow) => {
    if (!id) return;
    const key = row.key;
    setGeneratingDraft(key);
    try {
      await apiJson('/api/v1/drafts', {
        method: 'POST',
        body: JSON.stringify({
          character_id: id,
          preset_name: row.name,
          preset_type: row.type,
          intensity: row.type === 'emotion' ? row.intensity : undefined,
          text: row.text || 'This is a sample sentence for voice preview.',
          instruct: row.instruct,
          language: 'English',
        }),
      });
      console.debug('POST /api/v1/drafts: draft queued for preset %s', row.key);
      // Switch to drafts tab so user sees the new entry (req #3)
      setTab('drafts');
      setDraftsLoading(true);
      await fetchDrafts();
      setDraftsLoading(false);
    } catch (e) {
      console.error('POST /api/v1/drafts failed:', e);
      handleError(e, 'Generate Draft');
    } finally {
      setGeneratingDraft(null);
    }
  }, [id, fetchDrafts]);

  const playDraft = useCallback(async (draftId: string) => {
    if (draftAudioLoading === draftId) return;
    setDraftAudioLoading(draftId);
    try {
      const data = await apiJson<{ draft: Draft }>(`/api/v1/drafts/${draftId}`);
      if (data.draft.audio_b64) {
        setDraftAudio({ id: draftId, audio_b64: data.draft.audio_b64, format: data.draft.audio_format });
      }
    } catch (e) {
      handleError(e, 'Play Draft');
    } finally {
      setDraftAudioLoading(null);
    }
  }, [draftAudioLoading]);

  const approveDraft = useCallback(async (draftId: string) => {
    if (!id) return;
    setApprovingDraft(draftId);
    try {
      await apiJson(`/api/v1/drafts/${draftId}/approve`, {
        method: 'POST',
        body: JSON.stringify({ character_id: id }),
      });
      // Refresh both tabs
      await fetchDrafts();
      fetchTemplates();
    } catch (e) {
      handleError(e, 'Approve Draft');
    } finally {
      setApprovingDraft(null);
    }
  }, [id, fetchDrafts]);

  const discardDraft = useCallback(async (draftId: string) => {
    setDiscardingDraft(draftId);
    try {
      const resp = await api(`/api/v1/drafts/${draftId}`, { method: 'DELETE' });
      if (!resp.ok && resp.status !== 204) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${resp.status}`);
      }
      setDrafts(prev => prev.filter(d => d.id !== draftId));
      if (draftAudio?.id === draftId) setDraftAudio(null);
    } catch (e) {
      handleError(e, 'Discard Draft');
    } finally {
      setDiscardingDraft(null);
    }
  }, [draftAudio]);

  // Sprint 5: Retry failed draft (req #6) — creates new draft via regenerate
  const retryDraft = useCallback(async (draftId: string) => {
    setRetryingDraft(draftId);
    try {
      await apiJson(`/api/v1/drafts/${draftId}/regenerate`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      console.debug('POST /api/v1/drafts/%s/regenerate: new draft queued', draftId);
      await fetchDrafts();
    } catch (e) {
      console.error('Retry draft failed:', e);
      handleError(e, 'Retry Draft');
    } finally {
      setRetryingDraft(null);
    }
  }, [fetchDrafts]);

  /* ── Template library ──────────────────────────────────────── */

  const fetchTemplates = useCallback(async () => {
    if (!id) return;
    try {
      const data = await apiJson<{ templates: TemplateSummary[]; total: number }>(
        `/api/v1/templates?character_id=${id}&limit=50`
      );
      setTemplates(data.templates || []);
      setTemplatesTotal(data.total ?? 0);
    } catch { /* silently ignore */ }
  }, [id]);

  useEffect(() => {
    if (tab === 'templates') {
      setTemplatesLoading(true);
      fetchTemplates().finally(() => setTemplatesLoading(false));
    }
  }, [tab, fetchTemplates]);

  const playTemplate = useCallback(async (templateId: string) => {
    if (templateAudioLoading === templateId) return;
    setTemplateAudioLoading(templateId);
    try {
      const data = await apiJson<{ template: Template }>(`/api/v1/templates/${templateId}`);
      setTemplateAudio({ id: templateId, audio_b64: data.template.audio_b64, format: data.template.audio_format });
    } catch (e) {
      handleError(e, 'Play Template');
    } finally {
      setTemplateAudioLoading(null);
    }
  }, [templateAudioLoading]);

  const deleteTemplate = useCallback(async (templateId: string) => {
    setDeletingTemplate(templateId);
    try {
      const resp = await api(`/api/v1/templates/${templateId}`, { method: 'DELETE' });
      if (!resp.ok && resp.status !== 204) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${resp.status}`);
      }
      setTemplates(prev => prev.filter(t => t.id !== templateId));
      if (templateAudio?.id === templateId) setTemplateAudio(null);
    } catch (e) {
      handleError(e, 'Delete Template');
    } finally {
      setDeletingTemplate(null);
    }
  }, [templateAudio]);

  const startRenameTemplate = (t: TemplateSummary) => {
    setRenamingTemplate(t.id);
    setRenameValue(t.name);
  };

  const saveRenameTemplate = useCallback(async (templateId: string) => {
    const name = renameValue.trim();
    if (!name) return;
    try {
      await apiJson(`/api/v1/templates/${templateId}`, {
        method: 'PATCH',
        body: JSON.stringify({ name }),
      });
      setTemplates(prev => prev.map(t => t.id === templateId ? { ...t, name } : t));
    } catch (e) {
      handleError(e, 'Rename Template');
    } finally {
      setRenamingTemplate(null);
    }
  }, [renameValue]);

  /* ── Error display helper ──────────────────────────────────── */

  const handleError = (e: unknown, context: string) => {
    const msg = (e as Error).message;
    let detail = msg;
    if (msg.includes('502') || msg.includes('503')) {
      detail = `${context}: GPU backend unreachable. Check connection status.`;
    } else if (msg.includes('504') || msg.includes('timeout')) {
      detail = `${context}: Request timed out. The GPU may be cold-starting (~30s).`;
    } else {
      detail = `${context}: ${msg}`;
    }
    setError(detail);
    setTimeout(() => setError(null), 10000);
  };

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

  // Sprint 5: savePreset available ONLY for custom presets (not builtins)
  const savePreset = async (row: PresetRow) => {
    setSavingPreset(row.key);
    setError(null);
    try {
      if (row.type === 'emotion') {
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

  /* ── Render ────────────────────────────────────────────────── */

  if (!character) return <div className="loading">Loading...</div>;

  const filteredPresets = presets.filter(p => {
    if (filter === 'emotions') return p.type === 'emotion';
    if (filter === 'modes') return p.type === 'mode';
    return true;
  });

  const activeDraftCount = drafts.filter(d => d.status === 'pending' || d.status === 'generating').length;

  return (
    <div className="character-page">
      {/* Header */}
      <div className="page-header">
        <button onClick={() => navigate('/')} className="btn-back">← Back</button>
        <h2>{character.name}</h2>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flash error">
          <span>⚠️ {error}</span>
          <div className="flash-actions">
            <button className="btn-sm btn-dismiss" onClick={() => setError(null)}>✕</button>
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

      {/* Technical info toggle */}
      <div className="technical-toggle">
        <button onClick={() => setShowTechnical(!showTechnical)} className="btn-link" style={{ fontSize: 12 }}>
          {showTechnical ? '🔧 Hide technical details' : '🔧 Show technical details'}
        </button>
      </div>

      {/* Tabs — Voice Library removed (Sprint 5) */}
      <div className="tab-bar">
        <button className={`tab ${tab === 'presets' ? 'active' : ''}`} onClick={() => setTab('presets')}>
          🎭 Presets ({presets.length})
        </button>
        <button className={`tab ${tab === 'drafts' ? 'active' : ''}`} onClick={() => setTab('drafts')}>
          📝 Drafts
          {draftsTotal > 0 && <span className="tab-badge">{draftsTotal}</span>}
          {activeDraftCount > 0 && (
            <span className="tab-badge-active" title={`${activeDraftCount} generating`} />
          )}
        </button>
        <button className={`tab ${tab === 'templates' ? 'active' : ''}`} onClick={() => setTab('templates')}>
          📋 Templates
          {templatesTotal > 0 && <span className="tab-badge">{templatesTotal}</span>}
        </button>
      </div>

      {/* ── Presets Tab ──────────────────────────────────────── */}
      {tab === 'presets' && (
        <section className="presets-tab">
          <div className="info-box">
            <strong>What are presets?</strong> Presets define how a character expresses emotions (joy, anger, fear...)
            and delivery modes (whispering, shouting, laughing...). Each preset has an instruction for the TTS model
            and sample text. Click <strong>📝 Draft</strong> to queue a voice generation — review it in the Drafts tab.
          </div>

          {showTechnical && (
            <div className="info-box technical">
              <strong>🔧 Technical:</strong> Draft uses <code>VoiceDesign</code> asynchronously — the job is queued
              on the server and processed by the GPU backend. Poll GET /api/v1/drafts every 3s to see status.
              Approve a draft to promote it to a reusable Template.
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
            </div>
          </div>

          <div className="preset-list">
            {filteredPresets.map(row => {
              const isExpanded = expanded === row.key;
              const isRefining = refineKey === row.key;
              const isDraftingThis = generatingDraft === row.key;

              return (
                <div key={row.key} className={`preset-row ${isExpanded ? 'expanded' : ''} ${!row.is_builtin ? 'custom-preset' : ''}`}>
                  {/* Compact header */}
                  <div className="preset-header" onClick={() => setExpanded(isExpanded ? null : row.key)}>
                    <div className="preset-label">
                      <span className={`preset-type ${row.type}`}>{row.type === 'emotion' ? '😊' : '🎤'}</span>
                      <strong>{row.name}</strong>
                      <span className={`badge intensity-${row.intensity}`}>{row.intensity}</span>
                      {!row.is_builtin && <span className="badge custom" title="Custom preset — editable and deletable">✎ custom</span>}
                    </div>
                    <div className="preset-summary">{row.instruct.slice(0, 60)}{row.instruct.length > 60 ? '...' : ''}</div>
                    {/* Sprint 5: Only Draft button on preset rows */}
                    <div className="preset-actions-compact">
                      <button
                        onClick={e => { e.stopPropagation(); generateDraft(row); }}
                        disabled={isDraftingThis}
                        className="btn-sm btn-draft"
                        title="Queue a voice draft — review and approve in the Drafts tab"
                      >
                        {isDraftingThis ? '⏳' : '📝 Draft'}
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
                        <label>Sample Text <span className="hint">(what to say in the draft clip)</span></label>
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

                      {/* Sprint 5 editor actions:
                          - Removed: Preview, Cast & Save, Override & Save, Reset
                          - Kept: Save Changes (custom presets only), Refine with AI, Draft */}
                      <div className="editor-actions">
                        <button
                          onClick={() => generateDraft(row)}
                          disabled={isDraftingThis}
                          className="btn-primary btn-sm btn-draft"
                          title="Queue a voice draft — review and approve in the Drafts tab"
                        >
                          {isDraftingThis ? '⏳ Queuing...' : '📝 Draft'}
                        </button>
                        {!row.is_builtin && (
                          <button
                            onClick={() => savePreset(row)}
                            disabled={savingPreset === row.key}
                            className="btn-sm"
                            title="Save changes to server"
                          >
                            {savingPreset === row.key ? '⏳ Saving...' : '✎ Save Changes'}
                          </button>
                        )}
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
                              <p className="hint">Instruct updated above. Click Draft to hear the change.</p>
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

      {/* ── Drafts Tab ───────────────────────────────────────── */}
      {tab === 'drafts' && (
        <section className="drafts-tab">
          <div className="info-box">
            <strong>Draft Queue</strong> — Generate a voice sample from any preset using the <strong>📝 Draft</strong> button.
            Drafts appear here while audio generates. Play to review, then <strong>Approve</strong> to save as a Template.
            Failed drafts can be retried.
          </div>

          {draftsLoading && drafts.length === 0 && (
            <p className="empty">Loading drafts…</p>
          )}

          {!draftsLoading && drafts.length === 0 && (
            <p className="empty">
              No drafts yet. Use the <strong>📝 Draft</strong> button on any preset to queue a voice generation.
            </p>
          )}

          {drafts.length > 0 && (
            <div className="draft-list">
              {drafts.map(draft => {
                const isApproving = approvingDraft === draft.id;
                const isDiscarding = discardingDraft === draft.id;
                const isRetrying = retryingDraft === draft.id;
                const isLoadingAudio = draftAudioLoading === draft.id;
                const showingAudio = draftAudio?.id === draft.id;

                return (
                  <div key={draft.id} className={`draft-card draft-status-${draft.status}`}>
                    <div className="draft-header">
                      <div className="draft-meta">
                        <span className={`draft-status-badge ${draft.status}`}>
                          {draft.status === 'pending' && '⏳ Pending'}
                          {draft.status === 'generating' && '🔄 Generating'}
                          {draft.status === 'ready' && '✅ Ready'}
                          {draft.status === 'failed' && '❌ Failed'}
                          {draft.status === 'approved' && '✓ Approved'}
                        </span>
                        <span className="draft-preset">
                          {draft.preset_type === 'emotion' ? '😊' : '🎤'} {draft.preset_name}
                          {draft.intensity && <span className={`badge intensity-${draft.intensity}`}>{draft.intensity}</span>}
                        </span>
                        {draft.duration_s && (
                          <span className="hint">{draft.duration_s.toFixed(1)}s</span>
                        )}
                      </div>
                      <div className="draft-actions">
                        {draft.status === 'ready' && (
                          <>
                            <button
                              onClick={() => playDraft(draft.id)}
                              disabled={isLoadingAudio}
                              className="btn-sm"
                              title="Load and play audio"
                            >
                              {isLoadingAudio ? '⏳' : showingAudio ? '🔊 Playing' : '▶ Play'}
                            </button>
                            <button
                              onClick={() => approveDraft(draft.id)}
                              disabled={isApproving}
                              className="btn-sm btn-approve"
                              title="Approve — save as Character Template"
                            >
                              {isApproving ? '⏳' : '✓ Approve'}
                            </button>
                          </>
                        )}
                        {draft.status === 'approved' && showingAudio && (
                          <button
                            onClick={() => playDraft(draft.id)}
                            disabled={isLoadingAudio}
                            className="btn-sm"
                            title="Play audio"
                          >
                            {isLoadingAudio ? '⏳' : '▶ Play'}
                          </button>
                        )}
                        {/* Sprint 5: Retry button on failed drafts (req #6) */}
                        {draft.status === 'failed' && (
                          <button
                            onClick={() => retryDraft(draft.id)}
                            disabled={isRetrying}
                            className="btn-sm btn-retry"
                            title="Retry — queue a new draft with the same parameters"
                          >
                            {isRetrying ? '⏳' : '↩ Retry'}
                          </button>
                        )}
                        <button
                          onClick={() => discardDraft(draft.id)}
                          disabled={isDiscarding || draft.status === 'generating'}
                          className="btn-sm btn-danger"
                          title={draft.status === 'generating' ? 'Cannot discard while generating' : 'Discard this draft'}
                        >
                          {isDiscarding ? '⏳' : '🗑'}
                        </button>
                      </div>
                    </div>

                    <p className="draft-instruct">🎯 {draft.instruct}</p>
                    <p className="draft-text">"{draft.text}"</p>

                    {draft.status === 'failed' && draft.error && (
                      <p className="draft-error">⚠ {draft.error}</p>
                    )}

                    {showingAudio && draftAudio && (
                      <div className="draft-audio">
                        <AudioPlayer audioBase64={draftAudio.audio_b64} format={draftAudio.format} />
                      </div>
                    )}

                    <div className="draft-footer">
                      <span className="hint">
                        {new Date(draft.created_at).toLocaleString()}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {/* ── Templates Tab ────────────────────────────────────── */}
      {tab === 'templates' && (
        <section className="templates-tab">
          <div className="info-box">
            <strong>Templates</strong> are approved voice references for this character. Each template captures a
            specific preset, delivery style, and audio sample. Approve a draft to add templates here.
          </div>

          {templatesLoading && templates.length === 0 && (
            <p className="empty">Loading templates…</p>
          )}

          {!templatesLoading && templates.length === 0 && (
            <p className="empty">
              No templates yet. Generate drafts in the <strong>📝 Drafts</strong> tab and approve the best ones.
            </p>
          )}

          {templates.length > 0 && (
            <div className="template-grid">
              {templates.map(tmpl => {
                const isDeletingThis = deletingTemplate === tmpl.id;
                const isRenaming = renamingTemplate === tmpl.id;
                const isLoadingAudio = templateAudioLoading === tmpl.id;
                const showingAudio = templateAudio?.id === tmpl.id;

                return (
                  <div key={tmpl.id} className="template-card">
                    <div className="template-header">
                      {isRenaming ? (
                        <div className="rename-form">
                          <input
                            value={renameValue}
                            onChange={e => setRenameValue(e.target.value)}
                            onKeyDown={e => {
                              if (e.key === 'Enter') saveRenameTemplate(tmpl.id);
                              if (e.key === 'Escape') setRenamingTemplate(null);
                            }}
                            className="rename-input"
                            autoFocus
                          />
                          <button onClick={() => saveRenameTemplate(tmpl.id)} className="btn-sm btn-approve">✓</button>
                          <button onClick={() => setRenamingTemplate(null)} className="btn-sm">✕</button>
                        </div>
                      ) : (
                        <span
                          className="template-name"
                          onClick={() => startRenameTemplate(tmpl)}
                          title="Click to rename"
                        >
                          {tmpl.name}
                          <span className="rename-hint">✎</span>
                        </span>
                      )}
                    </div>

                    <div className="template-meta">
                      <span className="draft-preset">
                        {tmpl.preset_type === 'emotion' ? '😊' : '🎤'} {tmpl.preset_name}
                        {tmpl.intensity && <span className={`badge intensity-${tmpl.intensity}`}>{tmpl.intensity}</span>}
                      </span>
                      {tmpl.duration_s && (
                        <span className="hint">{tmpl.duration_s.toFixed(1)}s</span>
                      )}
                    </div>

                    <p className="draft-instruct">🎯 {tmpl.instruct}</p>
                    <p className="draft-text">"{tmpl.text}"</p>

                    <div className="template-actions">
                      <button
                        onClick={() => playTemplate(tmpl.id)}
                        disabled={isLoadingAudio}
                        className="btn-sm"
                        title="Load and play template audio"
                      >
                        {isLoadingAudio ? '⏳' : showingAudio ? '🔊 Playing' : '▶ Play'}
                      </button>
                      <button
                        onClick={() => deleteTemplate(tmpl.id)}
                        disabled={isDeletingThis}
                        className="btn-sm btn-danger"
                        title="Delete this template"
                      >
                        {isDeletingThis ? '⏳' : '🗑'}
                      </button>
                    </div>

                    {showingAudio && templateAudio && (
                      <div className="draft-audio">
                        <AudioPlayer audioBase64={templateAudio.audio_b64} format={templateAudio.format} />
                      </div>
                    )}

                    <div className="draft-footer">
                      <span className="hint">{new Date(tmpl.created_at).toLocaleString()}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
