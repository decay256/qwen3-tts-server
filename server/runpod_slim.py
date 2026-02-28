"""Slim RunPod handler — inference only.

Models are loaded from the Network Volume (/runpod-volume/huggingface/).
On first boot, models are downloaded from HuggingFace to the volume.
Subsequent boots load from local NVMe storage (~30s).

Supported endpoints:
  /api/v1/status              — health check
  /api/v1/voices/design       — VoiceDesign synthesis
  /api/v1/tts/synthesize      — Clone-based synthesis (with ref audio)
  /api/v1/voices/clone-prompt — Create a reusable clone prompt
  /api/v1/tts/clone-prompt    — Synthesize with a saved clone prompt
"""

import base64
import gc
import logging
import os
import sys
import time
import traceback

import runpod

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("tts-slim")

def _wav_to_bytes(wav_data, sr: int) -> tuple:
    """Convert wav tensor/array + sample rate to WAV bytes and duration."""
    import io
    import soundfile as sf
    import numpy as np
    if hasattr(wav_data, 'numpy'):
        wav_data = wav_data.numpy()
    wav_data = np.asarray(wav_data).flatten()
    duration = len(wav_data) / sr
    buf = io.BytesIO()
    sf.write(buf, wav_data, sr, format='WAV')
    return buf.getvalue(), duration


# ── State ───────────────────────────────────────────────────────────
engine = None
init_error = None
init_done = False


def ensure_models_cached():
    """Download models to network volume if not already present."""
    hf_home = os.environ.get("HF_HOME", "/runpod-volume/huggingface")
    os.makedirs(hf_home, exist_ok=True)
    os.environ["HF_HOME"] = hf_home

    from huggingface_hub import snapshot_download
    models = [
        "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    ]
    for model_id in models:
        cache_dir = os.path.join(hf_home, "hub")
        # Check if already cached
        model_dir_name = f"models--{model_id.replace('/', '--')}"
        if os.path.exists(os.path.join(cache_dir, model_dir_name, "snapshots")):
            logger.info("Model %s already cached", model_id)
        else:
            logger.info("Downloading %s to network volume...", model_id)
            snapshot_download(model_id, cache_dir=cache_dir)
            logger.info("Downloaded %s", model_id)


def init():
    """Load models — called lazily on first request."""
    global engine, init_error, init_done
    if init_done:
        return
    init_done = True

    # Warn loudly if no API key is configured.  RunPod has its own auth layer
    # so unauthenticated workers are still protected, but operators should set
    # API_KEY so that callers can't spoof requests via the input payload.
    if not os.environ.get("API_KEY"):
        logger.warning("No API_KEY configured — requests are unauthenticated")

    t0 = time.time()
    try:
        logger.info("=== TTS Slim Init ===")
        logger.info("CWD: %s", os.getcwd())

        # Add app dir to path
        app_dir = os.path.dirname(os.path.abspath(__file__))
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)

        import torch
        logger.info("Torch %s, CUDA: %s, GPU: %s",
                     torch.__version__, torch.cuda.is_available(),
                     torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")

        # Ensure models on volume
        ensure_models_cached()

        # Load engine
        from server.tts_engine import TTSEngine
        engine = TTSEngine()
        engine.load_models()
        logger.info("Models loaded: %s in %.1fs", list(engine._models.keys()), time.time() - t0)

    except Exception:
        init_error = traceback.format_exc()
        logger.error("INIT FAILED:\n%s", init_error)


# ── Handler ─────────────────────────────────────────────────────────

def handler(event):
    inp = event.get("input", {})
    endpoint = inp.get("endpoint", "/api/v1/status")
    body = inp.get("body", {})

    # API key check
    api_key = os.environ.get("API_KEY", "")
    req_key = inp.get("api_key", "")
    if api_key and req_key != api_key:
        return {"error": "Invalid API key"}

    # Lazy init
    if not init_done:
        init()
    if init_error:
        return {"error": f"Init failed: {init_error}"}

    try:
        if endpoint == "/api/v1/status":
            import torch
            return {
                "status": "running",
                "models_loaded": list(engine._models.keys()) if engine else [],
                "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none",
                "gpu_mem_mb": round(torch.cuda.memory_allocated() / 1024 / 1024, 1) if torch.cuda.is_available() else 0,
            }

        elif endpoint == "/api/v1/voices/design":
            text = body["text"]
            instruct = body["instruct"]
            language = body.get("language", "English")
            wav_data, sr = engine.generate_voice_design(text, instruct, language)
            audio_bytes, duration = _wav_to_bytes(wav_data, sr)
            gc.collect()
            return {
                "audio": base64.b64encode(audio_bytes).decode(),
                "duration_s": round(duration, 2),
                "format": "wav",
            }

        elif endpoint == "/api/v1/tts/synthesize":
            # Clone synthesis with ref audio
            text = body["text"]
            ref_audio_bytes = base64.b64decode(body["ref_audio"])
            ref_audio_b64 = base64.b64encode(ref_audio_bytes).decode()  # re-encode for engine
            ref_text = body.get("ref_text", "")
            language = body.get("language", "Auto")
            # Correct arg order: text, ref_audio_b64, ref_text, language
            wav_data, sr = engine.generate_voice_clone(text, ref_audio_b64, ref_text, language)
            audio_bytes, duration = _wav_to_bytes(wav_data, sr)
            gc.collect()
            return {
                "audio": base64.b64encode(audio_bytes).decode(),
                "duration_s": round(duration, 2),
                "format": "wav",
            }

        elif endpoint == "/api/v1/voices/clone-prompt":
            # Create a clone prompt and return the tensor data
            ref_audio_bytes = base64.b64decode(body["audio"])
            ref_audio_b64 = base64.b64encode(ref_audio_bytes).decode()  # re-encode for engine
            ref_text = body.get("ref_text", "")
            name = body["name"]
            # Engine takes (ref_audio_b64, ref_text) — name is NOT an engine arg
            prompt_data = engine.create_clone_prompt(ref_audio_b64, ref_text)
            gc.collect()
            # Serialize prompt to base64 for transport
            import io, torch
            buf = io.BytesIO()
            torch.save(prompt_data, buf)
            return {
                "prompt_data": base64.b64encode(buf.getvalue()).decode(),
                "name": name,
            }

        elif endpoint == "/api/v1/tts/clone-prompt":
            # Synthesize with a pre-computed clone prompt (sent as base64 tensor)
            import io, torch
            prompt_bytes = base64.b64decode(body["prompt_data"])
            prompt_data = torch.load(io.BytesIO(prompt_bytes), weights_only=False)
            text = body["text"]
            language = body.get("language", "Auto")
            wav_data, sr = engine.synthesize_with_clone_prompt(text=text, prompt_item=prompt_data, language=language)
            audio_bytes, duration = _wav_to_bytes(wav_data, sr)
            gc.collect()
            return {
                "audio": base64.b64encode(audio_bytes).decode(),
                "duration_s": round(duration, 2),
                "format": "wav",
            }

        else:
            return {"error": f"Unknown endpoint: {endpoint}"}

    except Exception as e:
        logger.exception("Handler error for %s", endpoint)
        return {"error": str(e)}


if __name__ == "__main__":
    logger.info("Starting TTS Slim handler (lazy init)...")
    if not os.environ.get("API_KEY"):
        logger.warning("No API_KEY configured — requests are unauthenticated (RunPod auth layer still applies)")
    runpod.serverless.start({"handler": handler})
