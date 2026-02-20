# Qwen3-TTS Server

GPU TTS render server using [Qwen3-TTS](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice) with a WebSocket reverse tunnel for [OpenClaw](https://openclaw.com).

Run Qwen3-TTS on your GPU machine and expose it securely to a remote server — no port forwarding needed.

## Architecture

```
┌──────────────────────┐                          ┌──────────────────────┐
│  Your GPU Machine    │                          │  OpenClaw / VPS      │
│                      │   outbound WSS tunnel    │                      │
│  server/main.py      │ ──────────────────────▶  │  bridge/server.py    │
│  • Qwen3-TTS models  │                          │  • HTTP API :8766    │
│  • RTX 4090 / etc    │  ◀── TTS requests ────   │  • WS relay :8765    │
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
git clone https://github.com/YOUR_USER/qwen3-tts-server.git
cd qwen3-tts-server
chmod +x scripts/setup.sh
./scripts/setup.sh
```

This creates a venv, installs `qwen-tts` + PyTorch + flash-attn, generates an auth token, and creates `.env`.

### 2. Configure

Edit `.env` — set `BRIDGE_URL` to your remote server's WebSocket address.

### 3. Start the bridge (remote server)

```bash
pip install websockets aiohttp python-dotenv
cp .env.example .env  # set AUTH_TOKEN to match GPU machine
python -m bridge.server
```

### 4. Start the GPU server

```bash
source .venv/bin/activate
python -m server.main
```

Models load on first run (~4GB download). After that, the server connects to the bridge and waits for requests.

## API Reference

All endpoints require `Authorization: Bearer <AUTH_TOKEN>` header.

### Generate Speech

```bash
POST /api/tts/generate
{
  "text": "Hello world",
  "voice": "Narrator",              # voice name or ID
  "voice_config": {                  # optional: for voice design
    "description": "Deep warm male narrator"
  },
  "output_format": "mp3"            # mp3, wav, ogg
}
# Returns: audio bytes with Content-Type header
```

### List Voices

```bash
GET /api/tts/voices
# Returns: [{"name": "...", "type": "builtin|designed|cloned", ...}]
```

### Clone Voice

```bash
POST /api/tts/clone
{
  "name": "my_voice",
  "reference_audio": "<base64 wav>",  # ~3 seconds of audio
  "description": "optional note"
}
```

### Health Check

```bash
GET /api/tts/health
# Returns: {"status": "ok", "gpu": "RTX 4090", "vram_used_gb": 5.2, ...}
```

## Voice Modes

Qwen3-TTS supports three modes, all available through the server:

| Mode | Model | Description |
|------|-------|-------------|
| **Custom Voice** | `Qwen3-TTS-12Hz-1.7B-CustomVoice` | 9 preset speakers + instruction control |
| **Voice Design** | `Qwen3-TTS-12Hz-1.7B-VoiceDesign` | Create voices from text descriptions |
| **Voice Clone** | `Qwen3-TTS-12Hz-1.7B-Base` | Clone any voice from a 3-second sample |

### Preset Speakers (Custom Voice)

Use `model.get_supported_speakers()` to list all 9 built-in speakers. Pass `speaker="Vivian"` + optional `instruct="Speak dramatically"`.

### Supported Languages

Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian. Use `"Auto"` for auto-detection.

## Models

| Key | HuggingFace ID | VRAM | Use Case |
|-----|---------------|------|----------|
| `custom_voice` | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | ~6GB | Preset speakers + instructions |
| `voice_design` | `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` | ~6GB | Voice from description |
| `base` | `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | ~6GB | Voice cloning |
| `custom_voice_small` | `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` | ~4GB | Smaller/faster preset voices |
| `base_small` | `Qwen/Qwen3-TTS-12Hz-0.6B-Base` | ~4GB | Smaller/faster cloning |

Configure which models to load in `.env` via `ENABLED_MODELS` (comma-separated keys).

## Security

- **Pre-shared token**: All API calls and tunnel connections authenticated via `AUTH_TOKEN`
- **HMAC-signed messages**: Tunnel messages signed with SHA-256 HMAC + timestamp (5-min window)
- **No inbound ports**: GPU machine connects outbound only
- **TLS support**: Bridge accepts WSS connections with optional custom CA cert
- **Rate limiting**: Configurable per-minute limit (default: 30)

## Configuration

See `.env.example` for all options. Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_TOKEN` | auto-generated | Shared secret for auth |
| `BRIDGE_URL` | `wss://...` | Remote bridge WebSocket URL |
| `ENABLED_MODELS` | `custom_voice,base` | Models to load |
| `CUDA_DEVICE` | `cuda:0` | GPU device |
| `RATE_LIMIT` | `30` | Requests per minute |
| `MAX_TEXT_LENGTH` | `5000` | Max chars per request |

## License

MIT
