"""TTS proxy routes — forwards to GPU relay with user auth.

These thin wrappers add auth and then delegate to the TTS relay.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from web.app.models.user import User
from web.app.routes.deps import get_current_user
from web.app.services import tts_proxy

router = APIRouter(prefix="/api/v1/tts", tags=["tts"])


# ── Status ──────────────────────────────────────────────────────────


@router.get("/status")
async def get_status(user: User = Depends(get_current_user)):
    """Get TTS server status (GPU connection, models loaded, etc.)."""
    return await tts_proxy.tts_get("/api/v1/status")


# ── Voice Library (read) ────────────────────────────────────────────


@router.get("/voices/characters")
async def list_characters(user: User = Depends(get_current_user)):
    """List all characters in the GPU voice library."""
    return await tts_proxy.tts_get("/api/v1/voices/characters")


@router.get("/voices/prompts")
async def list_prompts(
    tags: str | None = Query(None),
    user: User = Depends(get_current_user),
):
    """List all voice prompts, optionally filtered by tags."""
    path = "/api/v1/voices/prompts"
    if tags:
        path += f"?tags={tags}"
    return await tts_proxy.tts_get(path)


@router.get("/voices/prompts/search")
async def search_prompts(
    character: str | None = Query(None),
    emotion: str | None = Query(None),
    intensity: str | None = Query(None),
    tags: str | None = Query(None),
    user: User = Depends(get_current_user),
):
    """Search prompts by character, emotion, intensity, tags."""
    params = {}
    if character:
        params["character"] = character
    if emotion:
        params["emotion"] = emotion
    if intensity:
        params["intensity"] = intensity
    if tags:
        params["tags"] = tags
    path = "/api/v1/voices/prompts/search"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        path += f"?{qs}"
    return await tts_proxy.tts_get(path)


@router.get("/voices/emotions")
async def list_emotions(user: User = Depends(get_current_user)):
    """List available emotion presets and modes."""
    return await tts_proxy.tts_get("/api/v1/voices/emotions")


# ── Voice Library (write) ───────────────────────────────────────────


class DesignRequest(BaseModel):
    text: str
    instruct: str
    language: str = "English"
    format: str = "wav"


@router.post("/voices/design")
async def design_voice(body: DesignRequest, user: User = Depends(get_current_user)):
    """Generate a single voice design clip."""
    return await tts_proxy.tts_post("/api/v1/voices/design", body.model_dump())


class CastRequest(BaseModel):
    character: str
    description: str
    emotions: list[str] | None = None
    intensities: list[str] | None = None
    modes: list[str] | None = None
    entries: dict | None = None
    language: str = "English"
    format: str = "wav"


@router.post("/voices/cast")
async def cast_voice(body: CastRequest, user: User = Depends(get_current_user)):
    """Run full emotion casting for a character."""
    return await tts_proxy.tts_post("/api/v1/voices/cast", body.model_dump(exclude_none=True))


@router.delete("/voices/prompts/{name}")
async def delete_prompt(name: str, user: User = Depends(get_current_user)):
    """Delete a voice prompt."""
    return await tts_proxy.tts_delete(f"/api/v1/voices/prompts/{name}")


# ── Synthesis ───────────────────────────────────────────────────────


class SynthesizeRequest(BaseModel):
    voice_prompt: str
    text: str
    language: str = "Auto"
    format: str = "wav"


@router.post("/synthesize")
async def synthesize(body: SynthesizeRequest, user: User = Depends(get_current_user)):
    """Synthesize text using a saved clone prompt."""
    return await tts_proxy.tts_post("/api/v1/tts/clone-prompt", body.model_dump())


# ── LLM Refinement ─────────────────────────────────────────────────


class RefineRequest(BaseModel):
    current_instruct: str
    base_description: str
    ref_text: str
    feedback: str


@router.post("/voices/refine")
async def refine_prompt(body: RefineRequest, user: User = Depends(get_current_user)):
    """Use LLM to refine a voice instruct based on feedback."""
    from web.app.services.llm_refine import refine_prompt as do_refine

    try:
        result = await do_refine(
            current_instruct=body.current_instruct,
            base_description=body.base_description,
            ref_text=body.ref_text,
            feedback=body.feedback,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"LLM response parsing failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")


# ── Batch Design ────────────────────────────────────────────────────


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


@router.post("/voices/design/batch")
async def batch_design(body: BatchDesignRequest, user: User = Depends(get_current_user)):
    """Batch VoiceDesign synthesis with optional clone prompt creation."""
    return await tts_proxy.tts_post(
        "/api/v1/voices/design/batch",
        body.model_dump(exclude_none=True),
    )


# ── Clone Prompt ────────────────────────────────────────────────────


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


@router.post("/voices/clone-prompt")
async def create_clone_prompt(body: CreateClonePromptRequest, user: User = Depends(get_current_user)):
    """Create a clone prompt from reference audio."""
    return await tts_proxy.tts_post(
        "/api/v1/voices/clone-prompt",
        body.model_dump(exclude_none=True),
    )


class BatchClonePromptItem(BaseModel):
    audio: str  # base64
    name: str
    ref_text: str | None = None
    tags: list[str] | None = None
    format: str = "wav"


class BatchClonePromptRequest(BaseModel):
    items: list[BatchClonePromptItem]


@router.post("/voices/clone-prompt/batch")
async def batch_clone_prompt(body: BatchClonePromptRequest, user: User = Depends(get_current_user)):
    """Batch create clone prompts from reference audio."""
    return await tts_proxy.tts_post(
        "/api/v1/voices/clone-prompt/batch",
        body.model_dump(exclude_none=True),
    )


# ── Audio Normalize ─────────────────────────────────────────────────


class NormalizeRequest(BaseModel):
    audio: str  # base64
    ref_audio: str  # base64
    strength: float = 0.5
    format: str = "wav"


@router.post("/audio/normalize")
async def normalize_audio(body: NormalizeRequest, user: User = Depends(get_current_user)):
    """Normalize audio formants toward a reference."""
    return await tts_proxy.tts_post("/api/v1/audio/normalize", body.model_dump())


# ── Voice Packages ──────────────────────────────────────────────────


@router.get("/voices/{voice_id}/package")
async def export_package(voice_id: str, user: User = Depends(get_current_user)):
    """Export a voice as a self-contained package."""
    return await tts_proxy.tts_get(f"/api/v1/tts/voices/{voice_id}/package")


@router.post("/voices/import")
async def import_package(user: User = Depends(get_current_user)):
    """Import a voice package."""
    # This would need multipart handling — pass through for now
    raise HTTPException(status_code=501, detail="Voice package import not yet available via web UI")


@router.post("/voices/sync")
async def sync_packages(user: User = Depends(get_current_user)):
    """Sync voice packages between servers."""
    return await tts_proxy.tts_post("/api/v1/tts/voices/sync", {})
