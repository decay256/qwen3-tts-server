# Requirements: Voice Library & Emotion Clone Prompt Support

## Overview
Extend the Qwen3-TTS server to support a voice reference library workflow:
1. Generate reference clips via VoiceDesign
2. Build and persist reusable clone prompts from those clips
3. Select clone prompts at synthesis time by name/tag
4. Optional: formant-normalize clips for timbre consistency

## Functional Requirements

### FR-1: Multi-Model Support
- Server loads both VoiceDesign (1.7B) and Base (1.7B) models
- Models can be loaded simultaneously on GPU (both fit on 4090)
- **Must support CPU/single-model mode** for testing (configurable via ENABLED_MODELS env var)
- Config-driven: `enabled_models: [voice_design, base]` or `enabled_models: [voice_design]`

### FR-2: Voice Design Endpoint
- `POST /api/v1/voices/design` — generate reference clip via VoiceDesign
- Input: text, language, instruct, format
- Returns: audio file (WAV preferred for reference quality)

### FR-3: Clone Prompt Management
- `POST /api/v1/voices/clone-prompt` — create persistent clone prompt from reference audio
  - Calls `create_voice_clone_prompt(ref_audio, ref_text)` on Base model
  - Serializes VoiceClonePromptItem (ref_code tensor, ref_spk_embedding tensor, metadata) via torch.save
  - Stores in `voice-prompts/{name}.prompt` + `{name}.json`
  - Supports name, tags, ref_text metadata
- `GET /api/v1/voices/prompts` — list all saved clone prompts
  - Optional `?tags=maya,angry` filter
- `DELETE /api/v1/voices/prompts/{name}` — remove a saved clone prompt

### FR-4: Clone Synthesis with Saved Prompts
- `POST /api/v1/tts/clone` — synthesize using a saved clone prompt
- Input: text, language, voice_prompt (name), format
- Loads serialized clone prompt (cached in memory via LRU)
- Calls `generate_voice_clone(text, language, voice_clone_prompt=prompt)`
- Returns: audio file

### FR-5: Prompt Listing & Filtering
- List endpoint returns: name, tags, ref_text, created_at, ref_audio_duration_s
- Filter by tags (AND logic)

### FR-6: Batch Endpoints (stretch goal)
- `POST /api/v1/voices/design/batch` — generate multiple reference clips
- `POST /api/v1/voices/clone-prompt/batch` — build clone prompts from multiple files
- Must not timeout — support background processing or generous timeouts

### FR-7: Audio Normalization (stretch goal)
- `POST /api/v1/audio/normalize` — formant-normalize audio relative to reference
- Uses praat-parselmouth for formant extraction
- Pure DSP operation, no model inference

## Non-Functional Requirements

### NFR-1: No Project-Specific Content
- No character names, novel references, or domain-specific logic in server code
- Server is a generic tool; clients decide what voices to create

### NFR-2: Persistence
- Clone prompts survive server restarts
- Serialization must be deterministic (same input → loadable output)
- Storage: `voice-prompts/` directory with `.prompt` (torch tensors) + `.json` (metadata)

### NFR-3: Performance
- LRU cache for loaded clone prompts (avoid disk I/O every synthesis call)
- Both models (~8-12GB total) fit in 4090 VRAM — verify and document
- Long batch operations must not block the event loop

### NFR-4: Platform Compatibility
- Server runs on Windows (PowerShell) with RTX 4090, Python via miniconda
- Also runs on Linux (droplet) for CPU testing
- Known: miniconda ffmpeg broken for MP3 — request WAV from GPU, convert on relay

### NFR-5: Testing
- All new endpoints must have tests (mocked, no real model loading)
- Tests run on CPU without GPU in <10s
- Existing 115 tests must continue to pass

## Data Model

### VoiceClonePromptItem (from qwen_tts)
```python
@dataclass
class VoiceClonePromptItem:
    ref_code: Optional[torch.Tensor]       # (T, Q) tokenized audio
    ref_spk_embedding: torch.Tensor        # (D,) speaker embedding
    x_vector_only_mode: bool
    icl_mode: bool
    ref_text: Optional[str] = None
```

### Prompt Metadata (JSON sidecar)
```json
{
  "name": "maya_angry_medium",
  "tags": ["maya", "angry", "medium"],
  "ref_text": "Do not tell me about acceptable risk...",
  "created_at": "2026-02-24T22:00:00Z",
  "ref_audio_duration_s": 6.2,
  "x_vector_only_mode": false,
  "icl_mode": true
}
```

## File Structure
```
voice-prompts/
├── {name}.prompt    # torch.save({'ref_code': ..., 'ref_spk_embedding': ..., ...})
├── {name}.json      # metadata sidecar
└── ...
```

## API Endpoints Summary

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/v1/voices/design | Generate reference clip via VoiceDesign |
| POST | /api/v1/voices/clone-prompt | Create persistent clone prompt |
| GET | /api/v1/voices/prompts | List saved clone prompts |
| GET | /api/v1/voices/prompts?tags=x,y | Filter prompts by tags |
| DELETE | /api/v1/voices/prompts/{name} | Delete a clone prompt |
| POST | /api/v1/tts/clone | Synthesize with saved clone prompt |
| POST | /api/v1/voices/design/batch | Batch design (stretch) |
| POST | /api/v1/voices/clone-prompt/batch | Batch clone prompts (stretch) |
| POST | /api/v1/audio/normalize | Formant normalization (stretch) |
