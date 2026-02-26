"""Standalone GPU server — FastAPI app with direct model access.

For deployment on RunPod serverless (load balancing mode) or any GPU host.
No tunnel/relay needed — serves TTS endpoints directly over HTTP.

Usage:
    uvicorn server.standalone:app --host 0.0.0.0 --port 8000
    # Or: PORT=80 python -m server.standalone

Environment variables:
    API_KEY         — Required. Bearer token for auth.
    ENABLED_MODELS  — Comma-separated models to load (default: voice_design,base)
    VOICES_DIR      — Voice files directory (default: ./voices)
    PROMPTS_DIR     — Clone prompts directory (default: ./voice-prompts)
    PORT            — Server port (default: 8000)
"""

from __future__ import annotations

import asyncio
import base64
import gc
import io
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── Globals (initialized at startup) ────────────────────────────────

engine = None
prompt_store = None
voice_manager = None
start_time = None

security = HTTPBearer()


def verify_api_key(creds: HTTPAuthorizationCredentials = Security(security)):
    """Validate Bearer token against API_KEY env var."""
    expected = os.environ.get("API_KEY", "")
    if not expected:
        raise HTTPException(500, "API_KEY not configured")
    if creds.credentials != expected:
        raise HTTPException(401, "Invalid API key")
    return creds.credentials


# ── Lifespan ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models at startup."""
    global engine, prompt_store, voice_manager, start_time
    start_time = time.time()

    logger.info("=" * 60)
    logger.info("Qwen3-TTS Standalone Server starting up")
    logger.info("=" * 60)

    from server.tts_engine import TTSEngine
    from server.prompt_store import PromptStore
    from server.voice_manager import VoiceManager

    engine = TTSEngine()
    logger.info("Loading TTS models...")
    engine.load_models()
    logger.info("Models loaded: %s", engine.get_loaded_models())

    prompts_dir = os.environ.get("PROMPTS_DIR", "./voice-prompts")
    prompt_store = PromptStore(prompts_dir)
    logger.info("Prompt store: %d prompts", len(prompt_store.list_prompts()))

    voices_dir = os.environ.get("VOICES_DIR", "./voices")
    voice_manager = VoiceManager(voices_dir, engine=engine)
    logger.info("Voice manager: %d voices", len(voice_manager.list_voices()))

    yield

    logger.info("Shutting down standalone server")


app = FastAPI(title="Qwen3-TTS", version="1.0.0", lifespan=lifespan)


# ── Health (no auth — RunPod needs this) ────────────────────────────

@app.get("/ping")
async def ping():
    return {"status": "healthy"}


@app.get("/api/v1/status")
async def status(key=Security(verify_api_key)):
    import torch
    return {
        "status": "running",
        "tunnel_connected": True,  # compatibility with relay API
        "models_loaded": engine.get_loaded_models() if engine else [],
        "prompts_count": len(prompt_store.list_prompts()) if prompt_store else 0,
        "uptime_s": round(time.time() - start_time, 1) if start_time else 0,
        "gpu_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


@app.get("/api/v1/debug")
async def debug(key=Security(verify_api_key)):
    import torch
    import psutil
    proc = psutil.Process()
    mem = proc.memory_info()
    return {
        "uptime_s": round(time.time() - start_time, 1) if start_time else 0,
        "memory_rss_mb": round(mem.rss / 1024 / 1024, 1),
        "gpu_memory_allocated_mb": round(torch.cuda.memory_allocated() / 1024 / 1024, 1) if torch.cuda.is_available() else 0,
        "gpu_memory_reserved_mb": round(torch.cuda.memory_reserved() / 1024 / 1024, 1) if torch.cuda.is_available() else 0,
        "models_loaded": engine.get_loaded_models() if engine else [],
        "prompts_count": len(prompt_store.list_prompts()) if prompt_store else 0,
    }


# ── Synthesis helpers ───────────────────────────────────────────────

def _audio_to_base64(audio_data: bytes) -> str:
    return base64.b64encode(audio_data).decode("utf-8")


def _gc_after_synthesis():
    gc.collect()


# ── Voice Design ────────────────────────────────────────────────────

class DesignRequest(BaseModel):
    text: str
    instruct: str
    language: str = "English"
    format: str = "wav"


@app.post("/api/v1/voices/design")
async def design_voice(body: DesignRequest, key=Security(verify_api_key)):
    if not engine or "voice_design" not in engine.get_loaded_models():
        raise HTTPException(503, "VoiceDesign model not loaded")

    audio_data, duration = await asyncio.to_thread(
        engine.synthesize_voice_design, body.text, body.instruct, body.language
    )
    _gc_after_synthesis()

    return {
        "audio": _audio_to_base64(audio_data),
        "duration_s": round(duration, 2),
        "format": "wav",
    }


class BatchDesignItem(BaseModel):
    name: str
    text: str
    instruct: str
    language: str = "English"
    tags: list[str] | None = None
    character: str | None = None
    emotion: str | None = None
    intensity: str | None = None
    description: str | None = None
    base_description: str | None = None


class BatchDesignRequest(BaseModel):
    items: list[BatchDesignItem]
    format: str = "wav"
    create_prompts: bool = False
    tags_prefix: list[str] | None = None


@app.post("/api/v1/voices/design/batch")
async def batch_design(body: BatchDesignRequest, key=Security(verify_api_key)):
    if not engine or "voice_design" not in engine.get_loaded_models():
        raise HTTPException(503, "VoiceDesign model not loaded")

    results = []
    for item in body.items:
        try:
            audio_data, duration = await asyncio.to_thread(
                engine.synthesize_voice_design, item.text, item.instruct, item.language
            )

            result: dict[str, Any] = {
                "name": item.name,
                "status": "ok",
                "audio": _audio_to_base64(audio_data),
                "duration_s": round(duration, 2),
            }

            if body.create_prompts:
                metadata = {
                    "character": item.character,
                    "emotion": item.emotion,
                    "intensity": item.intensity,
                    "description": item.description,
                    "instruct": item.instruct,
                    "base_description": item.base_description,
                    "tags": (body.tags_prefix or []) + (item.tags or []),
                }
                prompt_result = await asyncio.to_thread(
                    engine.create_clone_prompt, audio_data, item.name, item.text, metadata=metadata
                )
                if prompt_result:
                    prompt_store.save_prompt(item.name, prompt_result,
                                            tags=metadata.get("tags", []), ref_text=item.text,
                                            metadata=metadata)
                    result["prompt_created"] = True

            results.append(result)
            _gc_after_synthesis()
        except Exception as e:
            results.append({"name": item.name, "status": "error", "error": str(e)})

    return {"results": results, "total": len(results)}


# ── Voice Casting ───────────────────────────────────────────────────

class CastRequest(BaseModel):
    character: str
    description: str
    emotions: list[str] | None = None
    intensities: list[str] | None = None
    modes: list[str] | None = None
    entries: list[dict] | None = None
    language: str = "English"
    format: str = "wav"


@app.post("/api/v1/voices/cast")
async def cast_voice(body: CastRequest, key=Security(verify_api_key)):
    from server.emotion_presets import build_casting_batch
    items = body.entries or build_casting_batch(
        body.character, body.description,
        emotions=body.emotions, intensities=body.intensities, modes=body.modes,
    )

    batch_req = BatchDesignRequest(
        items=[BatchDesignItem(**item) for item in items],
        format=body.format,
        create_prompts=True,
    )
    return await batch_design(batch_req, key)


# ── Clone Prompt CRUD ───────────────────────────────────────────────

@app.get("/api/v1/voices/prompts")
async def list_prompts(tags: str | None = None, key=Security(verify_api_key)):
    all_prompts = prompt_store.list_prompts(tags=tags.split(",") if tags else None)
    return {"prompts": all_prompts}


@app.get("/api/v1/voices/prompts/search")
async def search_prompts(
    character: str | None = None,
    emotion: str | None = None,
    intensity: str | None = None,
    tags: str | None = None,
    key=Security(verify_api_key),
):
    results = prompt_store.search_prompts(
        character=character, emotion=emotion, intensity=intensity,
        tags=tags.split(",") if tags else None,
    )
    return {"prompts": results}


@app.get("/api/v1/voices/characters")
async def list_characters(key=Security(verify_api_key)):
    return {"characters": prompt_store.list_characters()}


@app.delete("/api/v1/voices/prompts/{name}")
async def delete_prompt(name: str, key=Security(verify_api_key)):
    prompt_store.delete_prompt(name)
    return {"status": "deleted", "name": name}


class CreateClonePromptRequest(BaseModel):
    audio: str  # base64
    name: str
    ref_text: str | None = None
    tags: list[str] | None = None
    format: str = "wav"
    character: str | None = None
    emotion: str | None = None
    intensity: str | None = None
    description: str | None = None
    instruct: str | None = None
    base_description: str | None = None


@app.post("/api/v1/voices/clone-prompt")
async def create_clone_prompt(body: CreateClonePromptRequest, key=Security(verify_api_key)):
    if not engine or "base" not in engine.get_loaded_models():
        raise HTTPException(503, "Base model not loaded")

    audio_bytes = base64.b64decode(body.audio)
    metadata = {
        "character": body.character, "emotion": body.emotion,
        "intensity": body.intensity, "description": body.description,
        "instruct": body.instruct, "base_description": body.base_description,
    }
    prompt_data = await asyncio.to_thread(
        engine.create_clone_prompt, audio_bytes, body.name, body.ref_text, metadata=metadata
    )
    if prompt_data:
        prompt_store.save_prompt(body.name, prompt_data,
                                tags=body.tags or [], ref_text=body.ref_text or "",
                                metadata=metadata)
    return {"status": "created", "name": body.name}


# ── Synthesis with Clone Prompt ─────────────────────────────────────

class SynthesizePromptRequest(BaseModel):
    voice_prompt: str
    text: str
    language: str = "Auto"
    format: str = "wav"


@app.post("/api/v1/tts/clone-prompt")
async def synthesize_with_prompt(body: SynthesizePromptRequest, key=Security(verify_api_key)):
    if not engine or "base" not in engine.get_loaded_models():
        raise HTTPException(503, "Base model not loaded")

    prompt_data = prompt_store.load_prompt(body.voice_prompt)
    if not prompt_data:
        raise HTTPException(404, f"Prompt '{body.voice_prompt}' not found")

    audio_data, duration = await asyncio.to_thread(
        engine.synthesize_with_clone_prompt, prompt_data, body.text, body.language
    )
    _gc_after_synthesis()

    return {
        "audio": _audio_to_base64(audio_data),
        "duration_s": round(duration, 2),
        "format": "wav",
    }


# ── Emotions/Presets ────────────────────────────────────────────────

@app.get("/api/v1/voices/emotions")
async def list_emotions(key=Security(verify_api_key)):
    from server.emotion_presets import EMOTION_PRESETS, MODE_PRESETS, EMOTION_ORDER, MODE_ORDER
    emotions = {name: {
        "instruct_medium": p.instruct_medium,
        "instruct_intense": p.instruct_intense,
        "ref_text_medium": p.ref_text_medium,
        "ref_text_intense": p.ref_text_intense,
    } for name, p in EMOTION_PRESETS.items()}
    modes = {name: {
        "instruct": p.instruct,
        "ref_text": p.ref_text,
    } for name, p in MODE_PRESETS.items()}
    return {"emotions": emotions, "modes": modes, "emotion_order": EMOTION_ORDER, "mode_order": MODE_ORDER}


# ── Standard Synthesis (design-based) ───────────────────────────────

class SynthesizeRequest(BaseModel):
    text: str
    voice: str = ""
    instruct: str = ""
    language: str = "Auto"
    format: str = "wav"


@app.post("/api/v1/tts/synthesize")
async def synthesize(body: SynthesizeRequest, key=Security(verify_api_key)):
    """Synthesize with VoiceDesign (instruct) or clone voice."""
    if body.instruct:
        audio_data, duration = await asyncio.to_thread(
            engine.synthesize_voice_design, body.text, body.instruct, body.language
        )
    else:
        raise HTTPException(400, "Provide 'instruct' for VoiceDesign synthesis")
    _gc_after_synthesis()
    return {"audio": _audio_to_base64(audio_data), "duration_s": round(duration, 2), "format": "wav"}


# ── Audio Normalize ─────────────────────────────────────────────────

class NormalizeRequest(BaseModel):
    audio: str
    ref_audio: str
    strength: float = 0.5
    format: str = "wav"


@app.post("/api/v1/audio/normalize")
async def normalize_audio(body: NormalizeRequest, key=Security(verify_api_key)):
    from server.audio_normalize import normalize_formants
    audio_bytes = base64.b64decode(body.audio)
    ref_bytes = base64.b64decode(body.ref_audio)
    result = await asyncio.to_thread(normalize_formants, audio_bytes, ref_bytes, body.strength)
    return {"audio": _audio_to_base64(result), "format": "wav"}


# ── Entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    port = int(os.environ.get("PORT", 8000))
    logger.info("Starting standalone server on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
