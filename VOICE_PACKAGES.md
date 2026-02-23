# Voice Package System

The Qwen3-TTS server includes a comprehensive voice package system for portable distribution, backup, and sharing of voices. Voice packages are self-contained `.voicepkg.zip` files that preserve all voice data and metadata.

## Overview

Voice packages solve the key problem that the `voices/` directory is gitignored — without a packaging system, voices would be lost when deploying to new servers or sharing configurations.

### What's Included in a Voice Package

Each `.voicepkg.zip` contains:

- **`meta.json`** — Complete metadata for voice reconstruction
- **`ref.wav`** — Reference audio (for cloned voices)
- **`ref_transcript.txt`** — Transcript of reference audio
- **`samples/`** — Directory for audition samples (future feature)

### Package Format

The `meta.json` file includes all necessary reconstruction metadata:

```json
{
  "format_version": 1,
  "voice_id": "maya_cloned",
  "name": "Maya",
  "display_name": "Maya (Cloned)",
  "voice_type": "cloned",
  "description": "Young woman, warm and expressive, slight vulnerability",
  "ref_text": "Oh my god, do you see this?",
  "ref_duration_s": 3.0,
  "ref_sample_rate": 24000,
  "source": "voice_design",
  "design_description": "Young woman, warm and expressive, slight vulnerability",
  "design_language": "English",
  "created_at": "2026-02-15T00:00:00Z",
  "casting_notes": "",
  "model_used": "Qwen3-TTS-12Hz-1.7B-Base",
  "package_created_at": "2026-02-23T22:00:00Z"
}
```

## API Endpoints

### Local Server (GPU)

- **`GET /api/v1/tts/voices/{voice_id}/package`** — Export voice package
- **`POST /api/v1/tts/voices/import`** — Import voice package
- **`POST /api/v1/tts/voices/sync`** — Export all voices for relay sync

### Remote Relay (Droplet)

- **`GET /api/v1/tts/voices/{voice_id}/package`** — Download voice package (forwarded to GPU)
- **`POST /api/v1/tts/voices/import`** — Upload voice package (forwarded to GPU)
- **`POST /api/v1/tts/voices/sync`** — Sync all voices from GPU to relay

## Usage Examples

### Export a Voice Package

```bash
curl -H "Authorization: Bearer $API_KEY" \
  http://your-relay.com:9800/api/v1/tts/voices/maya_cloned/package \
  -o maya_cloned.voicepkg.zip
```

### Import a Voice Package

```bash
curl -H "Authorization: Bearer $API_KEY" \
  -F "file=@maya_cloned.voicepkg.zip" \
  http://your-relay.com:9800/api/v1/tts/voices/import
```

### Sync All Voices

```bash
curl -H "Authorization: Bearer $API_KEY" \
  -X POST http://your-relay.com:9800/api/v1/tts/voices/sync
```

## Python API

### Using VoicePackager Directly

```python
from server.voice_manager import VoiceManager
from server.voice_packager import VoicePackager

# Initialize
vm = VoiceManager('./voices')
packager = VoicePackager(vm)

# Export a single voice
package_path = packager.export_package('maya_cloned', 'maya.voicepkg.zip')

# Import a voice package
voice = packager.import_package('maya.voicepkg.zip')

# Export all voices
packages = packager.export_all('./backup/')
```

### Working with Bytes (for API transfer)

```python
# Export as bytes
package_path = packager.export_package(voice_id)
with open(package_path, 'rb') as f:
    package_bytes = f.read()

# Import from bytes
voice = packager.import_package(package_bytes)
```

## Auto-Sync Behavior

The system automatically syncs new voices to the relay after:

- Voice cloning via `/api/v1/tts/clone`
- Voice importing via `/api/v1/tts/voices/import`

This ensures the relay always has the latest voice packages for distribution.

## Demo Script

Run the included demo to see the full export/import workflow:

```bash
python demo_voice_packaging.py
```

This script:

1. Exports all existing voices as packages
2. Clears the voice catalog
3. Imports all packages to restore voices
4. Verifies all voices are correctly restored with metadata

## Use Cases

### Backup and Restore

```bash
# Backup all voices
curl -H "Authorization: Bearer $API_KEY" \
  -X POST http://relay:9800/api/v1/tts/voices/sync

# Later, restore a specific voice
curl -H "Authorization: Bearer $API_KEY" \
  -F "file=@voice_backup.voicepkg.zip" \
  http://relay:9800/api/v1/tts/voices/import
```

### Voice Distribution

Share curated voice collections by distributing `.voicepkg.zip` files. Recipients can import them directly without losing reference audio or metadata.

### Server Migration

When deploying to a new server:

1. Export all voices from the old server
2. Transfer the package files
3. Import them on the new server
4. All voices are restored with complete fidelity

## Architecture Notes

### Tunnel Protocol

Voice packages are transported over the WebSocket tunnel as base64-encoded JSON. The relay automatically decodes packages for HTTP download and encodes uploads for tunnel forwarding.

### Metadata Preservation

The system preserves all voice metadata including:

- Original design descriptions and languages
- Reference transcripts (from Whisper)
- Creation timestamps and source attribution
- Casting notes and display names
- Audio metadata (duration, sample rate)

### File Organization

Cloned voices store reference audio in voice-specific directories:

```
voices/
├── maya_cloned/
│   ├── ref.wav
│   └── meta.json
└── catalog.json
```

Voice packages preserve this organization and reconstruct it on import.

## Error Handling

The system validates packages on import:

- **Format validation** — Checks for required fields and correct format version
- **Duplicate prevention** — Prevents importing voices that already exist
- **Audio validation** — Verifies reference audio can be loaded
- **Metadata validation** — Ensures all required metadata is present

## Security

Voice packages are authenticated through the same API key system as other endpoints. The packages themselves are not encrypted but contain no sensitive data beyond voice model parameters.