# Qwen3-TTS Server

GPU TTS render server using [Qwen3-TTS](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice) with a WebSocket reverse tunnel for [OpenClaw](https://openclaw.com).

Run Qwen3-TTS on your GPU machine and expose it securely to a remote server — no port forwarding needed.

## Architecture

```
┌──────────────────────┐                          ┌──────────────────────┐
│  Your GPU Machine    │                          │  OpenClaw / VPS      │
│                      │   outbound WSS tunnel    │                      │
│  server/main.py      │ ──────────────────────▶  │  bridge/server.py    │
│  • Qwen3-TTS models  │                          │  • HTTP API :9800    │
│  • RTX 4090 / etc    │  ◀── TTS requests ────   │  • WS relay          │
│  • Voice clone/design │  ──── audio back ─────▶  │  • Auth + rate limit │
└──────────────────────┘                          └──────────────────────┘
         GPU side                                      Cloud side
     (no open ports)                              (public IP required)
```

## Requirements

- **GPU machine:** Python 3.10+, NVIDIA GPU with 6GB+ VRAM, CUDA 12+
- **Remote server:** Python 3.10+, public IP

## Quick Start

### 1. Setup (GPU machine)

```bash
git clone <repo-url>
cd qwen3-tts-server
./scripts/setup.sh    # creates venv, installs deps
cp config.example.yaml config.yaml
# Edit config.yaml — set api_key and remote.host
```

### 2. Start the relay (remote server)

```bash
python -m server.remote_relay
```

### 3. Start the GPU server

```bash
source .venv/bin/activate
python -m server.local_server
```

Models download on first run (~4GB). Server connects to relay via WebSocket tunnel.

## API Reference

All endpoints require `Authorization: Bearer <API_KEY>` header.

### GET /api/v1/status

Health check and server info.

```json
// Response
{
  "status": "ok",
  "gpu": "NVIDIA RTX 4090",
  "vram_used_gb": 5.2,
  "vram_total_gb": 24.0,
  "models_loaded": ["voice_design", "base"],
  "voices_count": 6,
  "uptime_seconds": 3600.5,
  "engine_ready": true
}
```

### GET /api/v1/tts/voices

List all available voices.

```json
// Response
{
  "voices": [
    {"voice_id": "designed_abc123", "name": "Narrator", "type": "designed", "description": "Deep warm male..."},
    {"voice_id": "cloned_def456", "name": "maya", "type": "cloned", "description": null}
  ]
}
```

### POST /api/v1/tts/synthesize

Generate speech. Two voice resolution modes:

**By voice_name (clone mode — consistent voice):**
```json
// Request
{
  "text": "Hello world",
  "voice_name": "maya",
  "instructions": "warm, gentle",
  "format": "mp3"
}
```

**By voice_id (design mode — stochastic):**
```json
// Request
{
  "text": "Hello world",
  "voice_id": "designed_abc123",
  "format": "mp3"
}
```

`voice_name` takes precedence if both provided. Cloned voices use saved reference audio for consistency. Designed voices generate from description each time (slightly different).

```json
// Response
{
  "audio": "<base64-encoded-audio>",
  "format": "mp3",
  "sample_rate": 24000,
  "voice_id": "cloned_def456"
}
```

### POST /api/v1/tts/design

Design a voice from a text description and get audio back. Used for auditioning — caller listens, then optionally saves via `/clone`.

```json
// Request
{
  "text": "The signal arrived at dawn.",
  "description": "Deep male narrator, gravitas, British accent",
  "language": "English",
  "format": "wav"
}
```

```json
// Response
{
  "audio": "<base64-encoded-audio>",
  "format": "wav",
  "sample_rate": 24000,
  "description": "Deep male narrator, gravitas, British accent"
}
```

### POST /api/v1/tts/clone

Save a reference audio sample as a named clone voice. The audio becomes the permanent reference for that voice name.

```json
// Request
{
  "voice_name": "maya",
  "reference_audio": "<base64-encoded-wav>"
}
```

```json
// Response
{
  "voice_id": "cloned_abc123",
  "name": "maya",
  "type": "cloned"
}
```

## Voice Audition Workflow

The recommended workflow for creating consistent character voices:

```
 Design → Audition → Pick → Clone → Render
   │         │         │       │        │
   │  Generate N       │  Save best    Use saved
   │  candidates       │  as clone     clone voice
   │  per character    │  reference    for all
   │                   │               chapters
   ▼                   ▼               ▼
 /design          listen &       /synthesize
 (stochastic)     compare        (voice_name=X)
```

### Using audition_voices.py

```bash
export QWEN_TTS_API_KEY="your-key"
export QWEN_TTS_URL="http://localhost:9800"

# Generate 5 voice candidates for all characters:
python3 skills/audiobook-render/scripts/audition_voices.py --all

# Or for one character:
python3 skills/audiobook-render/scripts/audition_voices.py --character maya

# With custom candidate count:
python3 skills/audiobook-render/scripts/audition_voices.py --character maya -n 8

# Listen to auditions/<character>/candidate_1.wav through candidate_5.wav
# Pick the best one:
python3 skills/audiobook-render/scripts/audition_voices.py --pick maya 3

# List saved voices on the server:
python3 skills/audiobook-render/scripts/audition_voices.py --list
```

After picking winners, `render_qwen.py` automatically detects saved clone voices and uses them instead of random design-mode generation.

## Voice Modes

| Mode | Model | Description |
|------|-------|-------------|
| **Custom Voice** | `Qwen3-TTS-12Hz-1.7B-CustomVoice` | 9 preset speakers + instruction control |
| **Voice Design** | `Qwen3-TTS-12Hz-1.7B-VoiceDesign` | Create voices from text descriptions |
| **Voice Clone** | `Qwen3-TTS-12Hz-1.7B-Base` | Clone any voice from a reference sample |

## Security

- Pre-shared API key authentication on all endpoints
- HMAC-signed tunnel messages with timestamp replay protection
- GPU machine connects outbound only (no open ports)
- Optional TLS with custom CA cert

## Configuration

See `config.example.yaml` for all options.

## License

MIT
