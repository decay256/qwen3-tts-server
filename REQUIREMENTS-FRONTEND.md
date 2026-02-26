# Requirements: Voice Studio Web Frontend

## Overview

A web-based UI for the Qwen3-TTS voice server. Covers voice casting (designing character voices), pre-rendering emotion/mode samples, editing rendered text, and LLM-assisted prompt refinement.

## 1. Authentication

### 1.1 Simple Email Login
- Email + password registration
- Email + password login (JWT or session token)
- Forgot password flow (email reset link)
- No OAuth — keep it simple

### 1.2 Session Management
- JWT tokens with expiry
- Refresh token rotation
- Logout (invalidate token)

### 1.3 Storage
- SQLite or Postgres (TBD) for user accounts
- Passwords: bcrypt hashed

---

## 2. Voice Casting

### 2.1 Create Character
- Name the character
- Define **base voice description** (physical traits only — pitch, texture, accent)
- Preview base voice with a test phrase (VoiceDesign one-shot)
- Save character to the voice library

### 2.2 Emotion Casting
- Select which emotions and intensities to generate (from presets, or define custom)
- **Cast all** — batch-generate all emotion × intensity clips
- **Cast single** — generate one specific emotion/intensity
- Each cast clip is played back in the UI for review
- Approved clips → saved as clone prompts on the GPU
- Rejected clips → option to **regenerate** (re-roll same settings) or **edit prompt** (tweak instruct text)

### 2.3 Mode Casting
- Same as emotions but for modes (laughing, whispering, etc.)
- Preview + approve/reject workflow

### 2.4 LLM-Assisted Refinement
- User describes what they don't like: "too nasal", "not angry enough", "sounds like a cartoon"
- LLM adjusts the instruct prompt and/or base description
- Generates a new clip with the modified prompt
- A/B comparison: play old vs new side-by-side
- Accept → replaces the old prompt; Reject → try again or revert

---

## 3. Voice Library

### 3.1 Character List
- Overview of all characters with prompt counts, available emotions/modes
- Backed by `GET /api/v1/voices/characters`

### 3.2 Character Detail
- Grid/list of all cast clips for a character
- Play any clip inline
- Delete individual prompts
- Re-cast individual prompts
- View metadata: instruct, base description, tags, duration

### 3.3 Search/Filter
- Filter by character, emotion, intensity, tags
- Backed by `GET /api/v1/voices/prompts/search`

---

## 4. Text Rendering

### 4.1 Script Editor
- Input text to render (single line or multi-line script)
- Assign character + emotion per line (manual dropdown or auto-annotated)
- Preview render: synthesize each line and play back
- **Regenerate** any individual line (re-roll with same prompt)
- **Edit** any line: change text, change emotion, change character

### 4.2 LLM Auto-Annotation
- Paste a script (dialogue + stage directions)
- LLM parses it and assigns: character, emotion, intensity per line
- User reviews/adjusts annotations before rendering

### 4.3 Export
- Concatenate all lines into a single MP3/WAV
- Download the full render
- Optionally download individual segments

---

## 5. Audio Playback

### 5.1 Inline Player
- Play/pause/scrub for any clip in the UI
- Waveform visualization (nice-to-have, not MVP)

### 5.2 A/B Comparison
- Side-by-side player for comparing two clips (old vs regenerated)

---

## 6. Technical Architecture

### 6.1 Frontend
- **React SPA** (Vite + TypeScript)
- Communicates with web backend via REST
- Audio playback client-side (Web Audio API or `<audio>` elements)
- Dark theme (consistent with Eigencore aesthetic)

### 6.2 Web Backend (new — separate FastAPI service)
- **FastAPI** (async, same pattern as Eigencore)
- **Same repo**, separate directory: `web/` (backend) + `frontend/` (React)
- Handles: auth, user management, character CRUD, LLM refinement
- Proxies TTS API calls to the relay (`localhost:9800`) with auth header
- LLM prompt refinement: configurable provider (OpenAI / Claude)
- Runs on a different port (e.g., `8080`), behind Caddy

### 6.3 Database
- **PostgreSQL** (asyncpg, same as Eigencore)
- Tables:
  - `users` (id, email, password_hash, verified, created_at)
  - `characters` (id, user_id, name, base_description, created_at)
  - `render_history` (id, user_id, character_id, text, prompt_name, created_at) — optional
- Alembic for migrations

### 6.4 Email (Resend)
- Password reset + email verification
- Resend API (no SMTP config needed, just API key)

### 6.5 Deployment
- **Docker Compose** on same droplet as relay
- Caddy reverse proxy: subdomain → web backend, auto-HTTPS
- Services: `web` (FastAPI), `frontend` (static build served by Caddy), `db` (Postgres)
- TTS relay stays separate (already running on port 9800)

### 6.6 Repo Layout
```
qwen3-tts-server/
├── server/              # existing TTS relay + local server
├── tests/               # existing TTS tests
├── web/                 # NEW: web backend (FastAPI)
│   ├── app/
│   │   ├── main.py
│   │   ├── core/        # config, security, email
│   │   ├── models/      # SQLAlchemy models
│   │   ├── routes/      # auth, characters, render, refine
│   │   └── services/    # LLM, TTS proxy
│   ├── alembic/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/            # NEW: React SPA
│   ├── src/
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
├── docker-compose.yml   # full stack
├── Caddyfile
└── ...
```

---

## 7. Non-Requirements (Out of Scope for MVP)

- Multi-user collaboration / sharing
- Payment / billing
- Real-time streaming synthesis
- Waveform editing
- Mobile-optimized UI
- Batch rendering of full novels (that's the novel-engine pipeline)

---

## 8. Decisions

| Question | Decision |
|----------|----------|
| Frontend framework | **React** (SPA) |
| Backend | **Separate FastAPI service**, same repo (like Eigencore) |
| LLM for refinement | **Configurable** — support OpenAI + Claude, selectable per deployment |
| Hosting | **Same droplet** as relay (for now) |
| Domain/TLS | **Custom subdomain** (Daniel will create), Caddy for auto-HTTPS |
| Email provider | **Resend** for transactional email (password reset, verification) |
| Database | **PostgreSQL** (same pattern as Eigencore) |
| Auth | **JWT** (email+password, bcrypt), no OAuth |

---

## 9. API Endpoints (Existing — Backend Already Supports)

| Feature | Endpoint | Status |
|---------|----------|--------|
| Cast voice (preset) | `POST /api/v1/voices/cast` | ✅ Done |
| Cast voice (matrix) | `POST /api/v1/voices/cast` | ✅ Done |
| Design single clip | `POST /api/v1/voices/design` | ✅ Done |
| Batch design | `POST /api/v1/voices/design/batch` | ✅ Done |
| Create clone prompt | `POST /api/v1/voices/clone-prompt` | ✅ Done |
| List prompts | `GET /api/v1/voices/prompts` | ✅ Done |
| Search prompts | `GET /api/v1/voices/prompts/search` | ✅ Done |
| List characters | `GET /api/v1/voices/characters` | ✅ Done |
| Delete prompt | `DELETE /api/v1/voices/prompts/{name}` | ✅ Done |
| Synthesize with prompt | `POST /api/v1/tts/clone-prompt` | ✅ Done |
| List emotions/modes | `GET /api/v1/voices/emotions` | ✅ Done |
| Server status | `GET /api/v1/status` | ✅ Done |

### New Endpoints Needed

| Feature | Endpoint | Notes |
|---------|----------|-------|
| Register | `POST /auth/register` | email, password |
| Login | `POST /auth/login` | returns JWT |
| Password reset request | `POST /auth/reset-request` | sends email |
| Password reset confirm | `POST /auth/reset-confirm` | token + new password |
| LLM refine prompt | `POST /api/v1/voices/refine` | text feedback → new instruct |
| Save character def | `POST /api/v1/characters` | name, base_description |
| List characters (user) | `GET /api/v1/characters` | user's characters |
