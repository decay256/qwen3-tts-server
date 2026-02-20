# Qwen3-TTS Server

Local GPU TTS rendering server with secure remote access. Runs Qwen3-TTS models on your RTX 4090 and exposes them to a remote server (e.g., OpenClaw) via a secure WebSocket reverse tunnel.

## Architecture

```
┌─────────────────────┐         WSS Tunnel          ┌──────────────────────┐
│  Your Machine (GPU) │ ──────────────────────────▶  │  Remote Server       │
│                     │                              │  (OpenClaw/VPS)      │
│  • Qwen3-TTS 1.7B  │  ◀── TTS requests ────────  │                      │
│  • RTX 4090 24GB    │  ──── Audio responses ────▶  │  • Bridge HTTP API   │
│  • Voice cloning    │                              │  • Auth + Rate limit │
└─────────────────────┘                              └──────────────────────┘
```

**Key design:** Your GPU machine connects *outbound* — no port forwarding, no firewall changes needed.

## Requirements

- **GPU machine:** NVIDIA GPU with 6+ GB VRAM (RTX 4090 recommended), Python 3.10+, CUDA 12+
- **Remote server:** Any Linux server with a public IP, Python 3.10+

## Quick Start

### 1. GPU Machine Setup

```bash
git clone https://github.com/dkondermann/qwen3-tts-server.git
cd qwen3-tts-server
./scripts/setup.sh
```

This will:
- Create a Python virtual environment
- Install PyTorch with CUDA support
- Install all dependencies
- Download Qwen3-TTS models (~4GB)
- Generate an auth token

### 2. Configure

```bash
cp config.example.yaml config.yaml
# Edit config.yaml — set your remote server IP and the generated auth token
```

### 3. Start the Bridge (on remote server)

```bash
pip install websockets aiohttp python-dotenv
export AUTH_TOKEN="your-token-here"
python -m bridge.server
```

### 4. Start the Local Server (on GPU machine)

```bash
source .venv/bin/activate
python -m server.main
```

The local server will:
1. Load Qwen3-TTS models onto your GPU
2. Connect to the remote bridge via WebSocket
3. Wait for TTS requests

## API

Once both sides are running, the bridge exposes an HTTP API on the remote server:

### Generate Speech
```bash
curl -X POST http://localhost:8766/api/tts/generate \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Elena opened a new log entry and began to type.",
    "voice": "Narrator",
    "output_format": "mp3"
  }' --output speech.mp3
```

### Voice Design (create voice from description)
```bash
curl -X POST http://localhost:8766/api/tts/generate \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "The ice had been dark for four million years.",
    "voice_config": {
      "description": "Deep male voice, warm storyteller quality, slight gravitas"
    },
    "output_format": "mp3"
  }' --output narration.mp3
```

### Voice Cloning (3-second sample)
```bash
curl -X POST http://localhost:8766/api/tts/clone \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "name=custom_narrator" \
  -F "reference_audio=@sample.wav"
```

### Health Check
```bash
curl http://localhost:8766/api/tts/health \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Voice Cast (The Deep Echoes)

Pre-configured voices for audiobook production in `config.example.yaml`:

| Character | Voice Type | Description |
|-----------|-----------|-------------|
| Narrator | Designed | Deep, warm male with gravitas |
| Maya | Designed | Young woman, warm, slight vulnerability |
| Elena | Designed | Mature woman, authoritative |
| Chen | Designed | Middle-aged man, calm, analytical |
| Raj | Designed | Young man, enthusiastic, energetic |
| Kim | Designed | Young woman, sharp, professional |

## Models

| Model | Params | VRAM | Use Case |
|-------|--------|------|----------|
| Qwen3-TTS-1.7B-VoiceDesign | 1.7B | ~6GB | Create voices from descriptions |
| Qwen3-TTS-1.7B-Base | 1.7B | ~6GB | Voice cloning from audio samples |
| Qwen3-TTS-0.6B-Base | 0.6B | ~4GB | Faster inference, lower quality |

## Security

- Pre-shared auth token for all API calls
- WebSocket tunnel supports TLS (WSS)
- No inbound ports required on GPU machine
- Rate limiting on bridge (default: 30 req/min)

## License

MIT
