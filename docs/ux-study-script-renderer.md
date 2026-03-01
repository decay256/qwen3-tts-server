# UX Study: Script-to-Audiobook Renderer

## Problem

We have:
- **Voice Studio** with character templates (approved voice+emotion combos with audio references)
- **Novel chapters** as annotated markdown (`@speaker`, `@emotion`, text segments)
- A **TTS backend** (Qwen3 VoiceDesign or clone prompts)

We need to connect them: upload a script, match segments to templates, render paragraph-by-paragraph, review, fix, and export a finished chapter audio.

## Current State

The audiobook-render skill (`render_qwen.py`) already:
- Parses annotated markdown into segments (speaker + emotion + text)
- Chunks long segments (500 char max)
- Renders each segment via `/api/v1/voices/design` or clone prompts
- Concatenates to single MP3 via ffmpeg

But it's a CLI tool with zero UI, zero review loop, and hardcoded voice mappings. You render blind and hope it's good.

## Proposed UX Flow

### Screen 1: Script Upload & Parse

```
┌─────────────────────────────────────────┐
│  📖 Script Renderer                     │
│                                         │
│  [Upload Markdown] or [Paste Text]      │
│                                         │
│  Script: chapter-07.md  ✅ Parsed       │
│  Segments: 47 │ Speakers: 3            │
│  Est. duration: ~8 min                  │
│                                         │
│  [Continue →]                           │
└─────────────────────────────────────────┘
```

Upload an annotated markdown file. System parses into segments with speaker/emotion/text. Shows summary. Supports both annotated (`@speaker`/`@emotion` comments) and plain markdown (auto-detect dialogue vs narration).

### Screen 2: Voice Casting (Template Matching)

```
┌─────────────────────────────────────────┐
│  🎭 Cast Voices                         │
│                                         │
│  narrator (28 segments)                 │
│  └─ Base: [Kira ▼] template: [calm ▼]  │
│     Overrides by emotion:               │
│     "tense" → [tense-urgent template ▼] │
│     "warm"  → [warm-narration template ▼]│
│     "whisper"→ [no match — Draft new?]  │
│                                         │
│  maya (12 segments)                     │
│  └─ Base: [Maya ▼] template: [neutral ▼]│
│     "excited" → [excited template ▼]    │
│     "fearful" → [no match — Draft new?] │
│                                         │
│  elena (7 segments)                     │
│  └─ [No character match — Create?]      │
│                                         │
│  [◀ Back]            [Cast & Continue →] │
└─────────────────────────────────────────┘
```

System auto-matches speakers to characters and emotions to templates:
1. **Speaker → Character**: Fuzzy match script speaker names to Voice Studio characters
2. **Emotion → Template**: Match `@emotion` tags to approved templates by preset name/type
3. **Gaps shown clearly**: Unmatched emotions offer "Draft new?" (jumps to CharacterPage to create one)
4. **Override per emotion**: User can swap any template assignment

**Matching algorithm:**
- Exact match: `@emotion: happy` → template with `preset_name=happy`
- Fuzzy: `@emotion: tense, urgent` → template with `preset_name=tense` or `fear`
- Fallback: Use character's base/neutral template if no emotion match
- Manual: User picks from dropdown of all character templates

### Screen 3: Segment Review & Render

```
┌─────────────────────────────────────────┐
│  📝 Segments (47)         [Render All]  │
│                                         │
│  ┌─ #1 narrator / warm ──────────────┐  │
│  │ "The team gathered in the          │  │
│  │  observation dome..."              │  │
│  │ 🎯 warm, clear, announcer         │  │
│  │ Template: warm-narration (Kira)    │  │
│  │ [▶ Play] [🔄 Re-render] [✏ Edit]  │  │
│  │ ✅ 4.2s                            │  │
│  └────────────────────────────────────┘  │
│                                         │
│  ┌─ #2 narrator / tense ─────────────┐  │
│  │ "The readings spiked without       │  │
│  │  warning..."                       │  │
│  │ 🎯 tense, urgent, accelerating    │  │
│  │ Template: tense-urgent (Kira)      │  │
│  │ [▶ Render] (not rendered yet)      │  │
│  └────────────────────────────────────┘  │
│                                         │
│  ┌─ #3 maya / excited ───────────────┐  │
│  │ "The crystalline structures..."    │  │
│  │ 🎯 warm, curious, professional    │  │
│  │ Template: [swap ▼]  ⚠ No match    │  │
│  │ [▶ Render]                         │  │
│  └────────────────────────────────────┘  │
│                                         │
│  Progress: 12/47 rendered │ 8 approved  │
│  [◀ Back]           [Export Chapter →]  │
└─────────────────────────────────────────┘
```

**Per-segment controls:**
- **Play**: Play rendered audio
- **Re-render**: Generate new audio (same template, new TTS run — variations are natural)
- **Edit**: Change the text or instruct before rendering
- **Swap template**: Pick a different template for this segment
- **Approve/Reject**: Mark segment as good (✅) or needs redo
- **Render All**: Batch-render all unrendered segments (queued as drafts)

**Key UX decisions:**
- Segments render as **drafts** in the existing draft system — reuses all the queue/status/retry infrastructure
- Each segment = 1 draft, tagged with `script_id` + `segment_index` for ordering
- Rendering is incremental: render a few, listen, adjust, render more
- No forced order — can jump to any segment

### Screen 4: Export

```
┌─────────────────────────────────────────┐
│  📦 Export Chapter                      │
│                                         │
│  Chapter: "The Ice"                     │
│  Segments: 47/47 rendered, 47 approved  │
│  Duration: 8:23                         │
│                                         │
│  Format: [MP3 ▼] Quality: [320kbps ▼]  │
│  □ Add 0.5s silence between segments    │
│  □ Normalize volume across segments     │
│                                         │
│  [⬇ Download MP3]                       │
│  [📤 Send to Discord]                   │
└─────────────────────────────────────────┘
```

Concatenates all approved segments via ffmpeg. Options for inter-segment silence, volume normalization, format.

---

## Architecture

### New Data Models

```
Script
├── id (UUID)
├── user_id (FK → User)
├── title (string)
├── raw_markdown (text)
├── created_at
└── updated_at

ScriptSegment
├── id (UUID)
├── script_id (FK → Script)
├── index (int) — ordering
├── speaker (string) — from @speaker tag
├── emotion (string) — from @emotion tag
├── text (string) — the actual content
├── character_id (FK → Character, nullable) — matched character
├── template_id (FK → Template, nullable) — matched template
├── draft_id (FK → Draft, nullable) — rendered audio
├── status: unmatched | matched | rendering | rendered | approved
└── instruct_override (text, nullable) — manual override
```

### New API Endpoints

```
POST   /api/v1/scripts              — Upload & parse markdown
GET    /api/v1/scripts              — List scripts
GET    /api/v1/scripts/{id}         — Get script with segments
DELETE /api/v1/scripts/{id}         — Delete script

POST   /api/v1/scripts/{id}/match   — Auto-match segments to templates
PATCH  /api/v1/scripts/{id}/segments/{idx} — Override match for segment

POST   /api/v1/scripts/{id}/render  — Render all unrendered segments (batch)
POST   /api/v1/scripts/{id}/segments/{idx}/render — Render single segment
POST   /api/v1/scripts/{id}/segments/{idx}/approve — Mark approved

POST   /api/v1/scripts/{id}/export  — Concatenate & return final audio
```

### Template Matching Algorithm

```python
def match_segment(segment, character, templates):
    """Match a segment's emotion to the best template."""
    
    # 1. Exact preset name match
    for t in templates:
        if t.preset_name == segment.emotion:
            return t
    
    # 2. Fuzzy: emotion words overlap
    emotion_words = set(segment.emotion.lower().split(', '))
    best_score, best_t = 0, None
    for t in templates:
        t_words = set(t.instruct.lower().split())
        overlap = len(emotion_words & t_words)
        if overlap > best_score:
            best_score, best_t = overlap, t
    if best_t and best_score > 0:
        return best_t
    
    # 3. Fallback: neutral/calm template or first available
    for t in templates:
        if t.preset_name in ('neutral', 'calm', 'default'):
            return t
    
    return templates[0] if templates else None
```

### How Rendering Works

Two modes, depending on whether we have a clone prompt or use VoiceDesign:

**Mode A — VoiceDesign (current):**
Each segment renders via `POST /api/v1/voices/design` with:
- `text`: segment text
- `instruct`: `{character.base_description}, {template.instruct}`
- `language`: from script metadata

**Mode B — Clone Prompts (future, better quality):**
Each segment renders via clone prompt endpoint with:
- `voice_name`: from template's associated clone prompt
- `text`: segment text  
- `instruct`: emotion/direction overlay

Mode B requires the GCS prompt sync feature (not yet built). Mode A works today.

### Integration with Existing Draft System

Script rendering reuses the draft infrastructure:
- Each segment render creates a Draft record (with `script_id` + `segment_index` metadata)
- Draft queue, polling, retry all work as-is
- Templates created via the existing approve flow

New fields on Draft model:
```python
script_id: Optional[UUID]      # FK → Script
segment_index: Optional[int]   # ordering within script
```

### Frontend Routes

```
/scripts                    — Script list
/scripts/:id                — Script detail (cast + segment review)
/scripts/:id/export         — Export page
```

### Rendering Pipeline (batch)

```
User clicks "Render All"
  → POST /api/v1/scripts/{id}/render
    → For each unrendered segment:
        1. Look up matched template
        2. Build instruct = base_description + template.instruct + emotion_override
        3. Create Draft with script_id, segment_index
        4. Queue TTS job (background task, same as draft system)
    → Return { queued: N }
  → Frontend polls draft list filtered by script_id
  → Segments update as drafts complete
```

### Scalability: Full Novel

For a full novel (~20 chapters × ~50 segments = 1000 segments):
- **Script list page** shows chapters with progress bars
- **Batch operations**: "Render All Chapters" queues everything
- **Resume**: Pick up where you left off — only unrendered segments queue
- **Consistent voices**: Once cast, all chapters use the same templates
- **Project-level casting**: Define voice cast once, apply to all chapters

Could add a `Project` model above `Script` for this:
```
Project → [Script, Script, ...] → [Segment, Segment, ...]
         ↓
       VoiceCast (speaker→character+default_template mapping)
```

---

## Implementation Phases

### Phase 1: Core (1 sprint, ~13pts)
- Script model + CRUD endpoints
- Markdown parser (reuse from render_qwen.py)
- Segment model with manual template assignment
- Basic segment list UI
- Single-segment render (creates Draft)
- Play/retry per segment

### Phase 2: Smart Matching (1 sprint)
- Auto-match algorithm
- Cast UI (speaker → character → template mapping)
- Batch render
- Segment approval workflow

### Phase 3: Export (half sprint)
- ffmpeg concatenation endpoint
- Export UI with format/quality options
- Download + Discord send

### Phase 4: Novel Scale (1 sprint)
- Project model (groups chapters)
- Project-level voice cast
- Batch chapter rendering
- Progress dashboard

---

## Open Questions

1. **Should we support re-ordering segments in the UI?** (Probably not — trust the script order)
2. **Should we edit the markdown source or just override per-segment?** (Override — keep source immutable)
3. **How to handle segment chunking?** (500-char chunks from render_qwen.py — expose as sub-segments or hide?)
4. **Cross-segment consistency?** (Same speaker+emotion should sound similar — templates help, but TTS is stochastic)
5. **Version control on scripts?** (Re-upload overwrites? Or keep history?) 
