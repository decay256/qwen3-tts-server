# Qwen3-TTS Server

Local GPU TTS server with secure remote access for [Qwen3-TTS](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base).

Run Qwen3-TTS on your local GPU (RTX 4090) and control it remotely from anywhere via a secure WebSocket tunnel.

## Architecture

```
┌─────────────────────┐         WebSocket Tunnel         ┌──────────────────────┐
│   Local GPU Machine │ ──────────────────────────────▶  │   Remote Relay       │
│                     │  (outbound connection, no open   │   (OpenClaw droplet) │
│  • Qwen3-TTS models│   ports on local machine)        │                      │
│  • RTX 4090 24GB   │                                  │  • REST API          │
│  • Voice cloning    │  ◀─── TTS requests ────          │  • Auth gateway      │
│  • Voice design     │  ──── Audio responses ──▶        │  • WebSocket hub     │
└─────────────────────┘                                  └──────────────────────┘
                                                                   ▲
                                                                   │ HTTPS
                                                                   │
                                                          ┌────────┴───────┐
                                                          │  API Clients   │
                                                          │  (OpenClaw,    │
                                                          │   scripts,     │
                                                          │   etc.)        │
                                                          └────────────────┘
```

## Features

- **Voice Cloning**: Clone any voice from a reference audio sample
- **Voice Design**: Create voices from text descriptions ("deep warm male narrator")
- **Secure Tunnel**: Local machine connects out — no ports to open, no firewall changes
- **API Key Auth**: All endpoints protected with shared secret
- **Auto-reconnect**: Tunnel reconnects automatically with exponential backoff
- **Streaming**: Support for chunked audio streaming for long texts
- **Audiobook Voice Cast**: Pre-configured voices for Narrator, Maya, Elena, Chen, Raj, Kim

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/decay256/qwen3-tts-server.git
cd qwen3-tts-server
```

### 2. Generate API keys

```bash
pip install pyyaml
python -m scripts.generate_keys
```

This creates `config.yaml` with a fresh API key. Copy it to both machines.

### 3. Setup local GPU machine

**Linux/WSL:**
```bash
chmod +x scripts/setup_local.sh
./scripts/setup_local.sh
```

**Windows PowerShell:**
```powershell
.\scripts\setup_local.ps1
```

### 4. Start the remote relay (on your server)

```bash
pip install -e .
python -m server.remote_relay
```

### 5. Start the local server (on your GPU machine)

```bash
python -m server.local_server
```

It connects to the remote relay automatically.

### 6. Test

```bash
python -m scripts.test_voices
```

## API Endpoints

All endpoints require `Authorization: Bearer <api_key>` header.

### `GET /api/v1/status`
Server status, GPU info, loaded models.

### `GET /api/v1/tts/voices`
List available voices.

### `POST /api/v1/tts/synthesize`
```json
{
  "text": "Hello world!",
  "voice_id": "Narrator",
  "instructions": "speak slowly with gravitas",
  "format": "mp3"
}
```
Returns audio file.

### `POST /api/v1/tts/clone`
Multipart: `reference_audio` (file) + `voice_name` (string).
Returns new voice info.

### `POST /api/v1/tts/design`
```json
{
  "description": "Deep warm male narrator voice",
  "name": "MyNarrator"
}
```
Returns new voice info.

## Python Client

```python
from client.tts_client import TTSClient

async with TTSClient("http://your-server:9800", "your-api-key") as client:
    # List voices
    voices = await client.list_voices()

    # Synthesize
    result = await client.synthesize("Hello!", voice_id="Narrator")
    result.save("output.mp3")

    # Clone a voice
    voice = await client.clone_voice("reference.wav", "MyVoice")

    # Design a voice
    voice = await client.design_voice("Cheerful young woman")
```

## Configuration

See `config.example.yaml` for all options. Key settings:

| Setting | Description |
|---------|-------------|
| `api_key` | Shared secret for auth |
| `remote.host` | Relay server IP/hostname |
| `remote.port` | Relay server port (default: 9800) |
| `remote.tls` | Enable TLS (recommended for production) |
| `local.device` | `cuda` or `cpu` |
| `local.models.base` | Base TTS model ID |
| `local.models.voice_design` | Voice design model ID |
| `voice_cast` | Pre-configured voice descriptions |

## Voice Cast (Audiobook)

Pre-configured voices for audiobook production:

| Character | Description |
|-----------|-------------|
| Narrator | Deep, warm male with gravitas |
| Maya | Young woman, warm and expressive |
| Elena | Mature woman, confident, Eastern European |
| Chen | Middle-aged man, calm, analytical |
| Raj | Young man, enthusiastic, energetic |
| Kim | Young woman, sharp, professional |

## Security

- **API key auth** on all endpoints (constant-time comparison)
- **No open ports** on local machine (outbound WebSocket only)
- **TLS support** for encrypted tunnel communication
- **Heartbeat** keeps tunnel alive, auto-reconnects on failure

## Requirements

- Python 3.10+
- NVIDIA GPU with 12GB+ VRAM (RTX 4090 recommended)
- CUDA 12.1+
- ~8GB disk for models

## License

MIT
