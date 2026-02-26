# Voice Library Workflow

The voice library is a system for creating, managing, and using character voices with emotional expressiveness. It follows a two-phase approach: **casting** (designing voices) and **rendering** (using them for production).

## Architecture

```
Phase 1: CASTING                     Phase 2: RENDERING
┌─────────────┐                      ┌─────────────────┐
│ VoiceDesign  │──→ WAV samples      │ Script + context │
│ + instruct   │──→ Clone prompts    │ + emotion tag    │
│ + base desc  │    with metadata    │                  │
└─────────────┘         │            └────────┬────────┘
                        │                     │
                        ▼                     ▼
                 ┌──────────────┐    ┌─────────────────┐
                 │ Prompt Store │◄───│ LLM selects best │
                 │ (on GPU)     │    │ matching prompt   │
                 └──────────────┘    └────────┬────────┘
                                              │
                                              ▼
                                     ┌─────────────────┐
                                     │ Clone synthesis  │
                                     │ prompt + text    │
                                     └─────────────────┘
```

## Phase 1: Casting

Casting creates emotion-specific voice samples and saves them as clone prompts. Each prompt captures both the voice identity AND the emotional tone.

### Step 1: Define the base voice

The base description should contain **ONLY physical traits** — no mood or emotion words:

```
Good: "Adult woman, low-mid pitch, distinctively husky, slight rasp, breathy onset, American accent"
Bad:  "Warm, sultry woman with a seductive voice"  ← mood words fight emotion modifiers
```

### Step 2: Cast using presets or custom entries

**Option A: Preset-based casting** (uses built-in emotion presets)

```bash
curl -X POST http://localhost:9800/api/v1/voices/cast \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "character": "kira",
    "description": "Adult woman, low-mid pitch, distinctively husky, slight rasp",
    "emotions": ["happy", "angry", "afraid"],
    "intensities": ["medium", "intense"],
    "modes": ["laughing", "whispering"],
    "format": "wav"
  }'
```

This generates 8 clips (3 emotions × 2 intensities + 2 modes), each saved as a clone prompt with rich metadata.

**Option B: Matrix-based casting** (custom entries)

```bash
curl -X POST http://localhost:9800/api/v1/voices/cast \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "character": "kira",
    "description": "Adult woman, low-mid pitch, distinctively husky",
    "entries": {
      "playful_teasing": {
        "direction": "playfully teasing, light mockery, one eyebrow raised",
        "text": "Oh really? You think you can just waltz in here and..."
      },
      "cold_fury": {
        "direction": "ice cold controlled rage, each word a knife",
        "text": "I gave you everything. And this is what you do with it."
      }
    }
  }'
```

Custom entries let you define any number of emotions/styles beyond the built-in presets.

### What gets saved

Each cast clip creates a clone prompt with metadata:

```json
{
  "name": "kira_angry_intense",
  "tags": ["kira", "angry", "intense"],
  "character": "kira",
  "emotion": "angry",
  "intensity": "intense",
  "description": "angry (intense): volcanic rage, SCREAMING, completely unhinged fury",
  "instruct": "Adult woman, husky voice, volcanic rage, SCREAMING...",
  "base_description": "Adult woman, low-mid pitch, distinctively husky",
  "ref_text": "HOW DARE YOU! After EVERYTHING I sacrificed!...",
  "ref_audio_duration_s": 8.5
}
```

## Phase 2: Rendering

At render time, an LLM selects the best matching clone prompt for each line of dialogue.

### Step 1: Query available prompts

**List all characters:**

```bash
curl http://localhost:9800/api/v1/voices/characters \
  -H "Authorization: Bearer $API_KEY"
```

Response:
```json
{
  "characters": [
    {
      "character": "kira",
      "prompt_count": 31,
      "emotions": ["afraid", "angry", "awe", "exhausted", "happy", "manic", "sad", "sarcastic", "tender"],
      "modes": ["choking", "crying", "distant", "gasping", "laughing", "screaming", "shouting", "whispering"]
    }
  ]
}
```

**Search prompts for a character:**

```bash
# All prompts for kira
curl "http://localhost:9800/api/v1/voices/prompts/search?character=kira" \
  -H "Authorization: Bearer $API_KEY"

# Kira angry prompts only
curl "http://localhost:9800/api/v1/voices/prompts/search?character=kira&emotion=angry" \
  -H "Authorization: Bearer $API_KEY"

# Specific intensity
curl "http://localhost:9800/api/v1/voices/prompts/search?character=kira&emotion=angry&intensity=intense" \
  -H "Authorization: Bearer $API_KEY"
```

The search response includes all metadata (description, instruct, tags) — enough for an LLM to pick the best match without loading audio.

### Step 2: Synthesize with selected prompt

```bash
curl -X POST http://localhost:9800/api/v1/tts/clone-prompt \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "voice_prompt": "kira_angry_intense",
    "text": "You had ONE chance and you threw it away!",
    "format": "wav"
  }'
```

The clone prompt provides voice consistency (same voice every time) with the emotional tone baked in from the casting phase.

## LLM Integration

The recommended flow for an LLM-driven rendering pipeline:

1. **Fetch the character's prompt catalog** via `GET /api/v1/voices/prompts/search?character=kira`
2. **For each line of dialogue**, the LLM receives:
   - The text to render
   - Scene context (mood, setting, what just happened)
   - The character's available prompts (name + description)
3. **LLM picks the best-matching prompt name**
4. **Synthesize** via `POST /api/v1/tts/clone-prompt` with `voice_prompt` = selected name

This approach is dynamic — you can add new emotion variants at any time by casting more prompts, and the LLM will automatically see them in the catalog.

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/voices/cast` | POST | Full casting workflow (preset or matrix mode) |
| `/api/v1/voices/emotions` | GET | List available emotion presets and modes |
| `/api/v1/voices/characters` | GET | List all characters with prompt counts |
| `/api/v1/voices/prompts` | GET | List all prompts (optional `?tags=` filter) |
| `/api/v1/voices/prompts/search` | GET | Search by `character`, `emotion`, `intensity`, `tags` |
| `/api/v1/voices/prompts/{name}` | DELETE | Delete a prompt |
| `/api/v1/voices/clone-prompt` | POST | Create a single clone prompt from audio |
| `/api/v1/voices/clone-prompt/batch` | POST | Batch create clone prompts |
| `/api/v1/tts/clone-prompt` | POST | Synthesize text using a saved clone prompt |
| `/api/v1/voices/design` | POST | One-off VoiceDesign synthesis |
| `/api/v1/voices/design/batch` | POST | Batch VoiceDesign synthesis (with optional prompt creation) |

## Built-in Presets

The server includes 9 emotions × 2 intensities + 13 modes as starter templates:

**Emotions:** happy, angry, afraid, sad, awe, tender, sarcastic, manic, exhausted
**Intensities:** medium, intense
**Modes:** laughing, crying, screaming, gasping, choking, stuttering, whispering, singsong, slurred, shouting, radio, narration, distant

Use `GET /api/v1/voices/emotions` to see all presets with their instruct strings and reference texts.

These are starting points — you can define any custom emotions via the matrix-based casting mode.
