/** Character detail — view prompts, cast emotions, preview/regenerate clips. */

import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiJson } from '../api/client';
import { AudioPlayer } from '../components/AudioPlayer';
import type { Character, VoicePrompt, DesignResult, RefineResult } from '../api/types';

export function CharacterPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [character, setCharacter] = useState<Character | null>(null);
  const [prompts, setPrompts] = useState<VoicePrompt[]>([]);
  const [preview, setPreview] = useState<{ audio: string; format: string } | null>(null);
  const [previewText, setPreviewText] = useState('Hello, this is a test of my voice.');
  const [previewInstruct, setPreviewInstruct] = useState('');
  const [generating, setGenerating] = useState(false);
  const [casting, setCasting] = useState(false);

  // Refine state
  const [refinePrompt, setRefinePrompt] = useState<VoicePrompt | null>(null);
  const [feedback, setFeedback] = useState('');
  const [refining, setRefining] = useState(false);
  const [refineResult, setRefineResult] = useState<RefineResult | null>(null);

  useEffect(() => {
    if (!id) return;
    apiJson<Character>(`/api/v1/characters/${id}`).then(c => {
      setCharacter(c);
      setPreviewInstruct(c.base_description);
    }).catch(() => navigate('/'));
  }, [id]);

  useEffect(() => {
    if (!character) return;
    apiJson<{ prompts: VoicePrompt[] }>(`/api/v1/tts/voices/prompts/search?character=${character.name.toLowerCase()}`)
      .then(d => setPrompts(d.prompts))
      .catch(() => {});
  }, [character]);

  const generatePreview = async () => {
    if (!previewInstruct.trim()) return;
    setGenerating(true);
    setPreview(null);
    try {
      const result = await apiJson<DesignResult>('/api/v1/tts/voices/design', {
        method: 'POST',
        body: JSON.stringify({
          text: previewText,
          instruct: previewInstruct,
          format: 'wav',
        }),
      });
      setPreview({ audio: result.audio, format: 'wav' });
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  const castEmotions = async () => {
    if (!character) return;
    setCasting(true);
    try {
      await apiJson('/api/v1/tts/voices/cast', {
        method: 'POST',
        body: JSON.stringify({
          character: character.name.toLowerCase(),
          description: character.base_description,
          format: 'wav',
        }),
      });
      // Refresh prompts
      const d = await apiJson<{ prompts: VoicePrompt[] }>(
        `/api/v1/tts/voices/prompts/search?character=${character.name.toLowerCase()}`
      );
      setPrompts(d.prompts);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setCasting(false);
    }
  };

  const synthesizePrompt = async (promptName: string) => {
    setGenerating(true);
    setPreview(null);
    try {
      const result = await apiJson<DesignResult>('/api/v1/tts/synthesize', {
        method: 'POST',
        body: JSON.stringify({
          voice_prompt: promptName,
          text: previewText,
          format: 'wav',
        }),
      });
      setPreview({ audio: result.audio, format: 'wav' });
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  const refineVoice = async () => {
    if (!refinePrompt || !feedback.trim() || !character) return;
    setRefining(true);
    try {
      const result = await apiJson<RefineResult>('/api/v1/tts/voices/refine', {
        method: 'POST',
        body: JSON.stringify({
          current_instruct: refinePrompt.instruct || character.base_description,
          base_description: character.base_description,
          ref_text: previewText,
          feedback,
        }),
      });
      setRefineResult(result);
      // Auto-set the new instruct for preview
      setPreviewInstruct(result.new_instruct);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setRefining(false);
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

  if (!character) return <div className="loading">Loading...</div>;

  // Group prompts by emotion
  const emotions = new Map<string, VoicePrompt[]>();
  for (const p of prompts) {
    const key = p.emotion || 'other';
    if (!emotions.has(key)) emotions.set(key, []);
    emotions.get(key)!.push(p);
  }

  return (
    <div className="character-page">
      <div className="page-header">
        <button onClick={() => navigate('/')} className="btn-back">← Back</button>
        <h2>{character.name}</h2>
        <p className="base-desc">{character.base_description}</p>
      </div>

      {/* Preview section */}
      <section className="preview-section">
        <h3>Voice Preview</h3>
        <textarea
          placeholder="Text to speak..."
          value={previewText}
          onChange={e => setPreviewText(e.target.value)}
          rows={2}
        />
        <textarea
          placeholder="Instruct (voice + emotion description)"
          value={previewInstruct}
          onChange={e => setPreviewInstruct(e.target.value)}
          rows={2}
        />
        <div className="preview-actions">
          <button onClick={generatePreview} disabled={generating} className="btn-primary">
            {generating ? 'Generating...' : '🔊 Generate Preview'}
          </button>
          <button onClick={castEmotions} disabled={casting} className="btn-secondary">
            {casting ? 'Casting...' : '🎭 Cast All Emotions'}
          </button>
        </div>
        {preview && <AudioPlayer audioBase64={preview.audio} format={preview.format} label="Preview" />}
      </section>

      {/* LLM Refine section */}
      <section className="refine-section">
        <h3>🤖 LLM Refinement</h3>
        <p className="hint">Describe what's wrong with the voice, and the LLM will suggest a better instruct.</p>
        <select
          value={refinePrompt?.name || ''}
          onChange={e => {
            const p = prompts.find(p => p.name === e.target.value);
            setRefinePrompt(p || null);
            setRefineResult(null);
          }}
        >
          <option value="">Select a prompt to refine...</option>
          {prompts.map(p => (
            <option key={p.name} value={p.name}>
              {p.name} — {p.description || p.emotion || 'base'}
            </option>
          ))}
        </select>
        {refinePrompt && (
          <>
            <textarea
              placeholder="What's wrong? (e.g., 'too nasal', 'not angry enough', 'sounds like a cartoon')"
              value={feedback}
              onChange={e => setFeedback(e.target.value)}
              rows={2}
            />
            <button onClick={refineVoice} disabled={refining} className="btn-primary">
              {refining ? 'Thinking...' : '✨ Refine'}
            </button>
          </>
        )}
        {refineResult && (
          <div className="refine-result">
            <p><strong>Explanation:</strong> {refineResult.explanation}</p>
            <p><strong>New instruct:</strong> <code>{refineResult.new_instruct}</code></p>
            {refineResult.new_base_description && (
              <p><strong>New base:</strong> <code>{refineResult.new_base_description}</code></p>
            )}
            <button onClick={generatePreview} className="btn-primary">
              🔊 Preview with new instruct
            </button>
          </div>
        )}
      </section>

      {/* Prompts grid */}
      <section className="prompts-section">
        <h3>Voice Library ({prompts.length} prompts)</h3>
        {Array.from(emotions.entries()).map(([emotion, emotionPrompts]) => (
          <div key={emotion} className="emotion-group">
            <h4>{emotion}</h4>
            <div className="prompt-grid">
              {emotionPrompts.map(p => (
                <div key={p.name} className="prompt-card">
                  <div className="prompt-header">
                    <span className="prompt-name">{p.name}</span>
                    {p.intensity && <span className={`badge ${p.intensity}`}>{p.intensity}</span>}
                  </div>
                  {p.description && <p className="prompt-desc">{p.description}</p>}
                  <div className="prompt-actions">
                    <button onClick={() => synthesizePrompt(p.name)} disabled={generating} className="btn-sm">
                      ▶ Play
                    </button>
                    <button onClick={() => deletePrompt(p.name)} className="btn-sm btn-danger">
                      🗑
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
        {prompts.length === 0 && (
          <p className="empty">No prompts yet. Use "Cast All Emotions" to generate them.</p>
        )}
      </section>
    </div>
  );
}
