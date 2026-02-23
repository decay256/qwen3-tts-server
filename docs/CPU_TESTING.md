# CPU Testing Report

## Summary

Tested Qwen3-TTS server on a DigitalOcean droplet (4 vCPU, 8GB RAM) to validate 
the full pipeline locally without GPU dependency.

## Key Findings

### Precision

| Precision | voice_design (1.7B) RAM | base_small (0.6B) RAM | Works? |
|-----------|------------------------|----------------------|--------|
| float32   | ~4.6GB (OOMs during synthesis) | ~2.5GB | ❌/✅ Loads but OOMs on 1.7B synthesis |
| bfloat16  | ~1.8GB load, ~4.9GB peak | ~1.0GB load, ~2.9GB peak | ✅ Both work |
| 4-bit (bitsandbytes) | N/A | N/A | ❌ `TypeError: cannot pickle 'dict_keys' object` |

**Recommendation:** Always use bfloat16 on CPU. It halves memory vs float32 with no 
compatibility issues. The qwen-tts library doesn't support bitsandbytes quantization.

### Synthesis Performance (CPU, bfloat16, 4 vCPU)

| Mode | Model | Text | Time | Output |
|------|-------|------|------|--------|
| Voice Design | voice_design (1.7B) | "Hello world" | **139s** | 23040 samples (1s audio) |
| Voice Clone | base_small (0.6B) | "Hello" (3s ref) | **>20min** (killed) | N/A |

Voice design is slow but usable for testing. Voice clone is impractical on CPU — 
the reference audio encoding dominates compute time regardless of output length.

### Model Loading

| Model | Precision | Load Time | RAM After Load |
|-------|-----------|-----------|----------------|
| base_small (0.6B) | bfloat16 | 5-7s | 1.0GB |
| base_small (0.6B) | float32 | 23-28s | 2.5GB |
| voice_design (1.7B) | bfloat16 | 5s | 1.8GB |
| voice_design (1.7B) | float32 | ~30s | 4.6GB |

### Pipeline Architecture

The full pipeline works end-to-end on CPU:
1. ✅ Remote relay (HTTP API on port 9800)
2. ✅ WebSocket tunnel (auth, heartbeat, keepalive)
3. ✅ Local server (model loading, request routing)
4. ✅ Voice manager (catalog, clone refs, designed voices)
5. ✅ TTS engine (CPU auto-detection, bfloat16)
6. ✅ Audio encoding + response through tunnel

### Issues Found

1. **float32 was default for CPU** — caused OOMs with 1.7B model. Fixed: now uses bfloat16.
2. **Long clone references** (24s) cause excessive RAM during encoding. 
   Recommendation: trim references to 3-5s.
3. **NNPACK warnings** on VPS CPUs — harmless, can be suppressed.
4. **Log buffering** hid output until process exit. Fix: use `PYTHONUNBUFFERED=1`.

## How to Run CPU Tests

### Quick model load test
```bash
cd /path/to/qwen3-tts-server
CUDA_DEVICE=cpu ENABLED_MODELS=base_small ./tts_env/bin/python -c "
from server.tts_engine import TTSEngine
from server import config
engine = TTSEngine()
engine.load_models()
print(engine.get_health())
"
```

### Full pipeline test (two modes)

**Mode 1: Voice Design**
```bash
CUDA_DEVICE=cpu ENABLED_MODELS=voice_design QWEN3_TTS_CONFIG=config-cpu-local.yaml \
  ./tts_env/bin/python -m server.remote_relay &
sleep 2
CUDA_DEVICE=cpu ENABLED_MODELS=voice_design QWEN3_TTS_CONFIG=config-cpu-local.yaml \
  ./tts_env/bin/python -m server.local_server &
sleep 10
curl -H "Authorization: Bearer test-local-key-12345" http://localhost:9800/api/v1/status
```

**Mode 2: Voice Clone** (very slow on CPU, GPU recommended)
```bash
CUDA_DEVICE=cpu ENABLED_MODELS=base_small QWEN3_TTS_CONFIG=config-cpu-local.yaml \
  ./tts_env/bin/python -m server.remote_relay &
sleep 2
CUDA_DEVICE=cpu ENABLED_MODELS=base_small QWEN3_TTS_CONFIG=config-cpu-local.yaml \
  ./tts_env/bin/python -m server.local_server &
sleep 30  # base_small loads slower in float32
```

## Production vs Testing

| | Production (GPU) | Testing (CPU) |
|--|-----------------|---------------|
| Precision | bfloat16 | bfloat16 |
| Flash attention | Yes | No (skipped automatically) |
| Models | voice_design + base (both loaded) | One at a time |
| Clone synthesis | ~2-5s | >20min (impractical) |
| Design synthesis | ~2-5s | ~139s |
| RAM needed | 6GB+ VRAM | 5GB+ system RAM |
