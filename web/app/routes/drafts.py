"""Draft routes — voice generation jobs queue.

POST   /api/v1/drafts                        — create draft + kick off background generation
GET    /api/v1/drafts                        — list (no audio_b64), frontend polls this
GET    /api/v1/drafts/{draft_id}             — full draft with audio_b64 (for playback)
DELETE /api/v1/drafts/{draft_id}             — discard
POST   /api/v1/drafts/{draft_id}/approve     — promote to Character Template
POST   /api/v1/drafts/{draft_id}/regenerate  — create new draft with same params
"""

import base64
import io
import logging
import wave
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from web.app.core.database import async_session, get_db
from web.app.models.character import Character
from web.app.models.draft import (
    Draft,
    DRAFT_STATUS_APPROVED,
    DRAFT_STATUS_FAILED,
    DRAFT_STATUS_GENERATING,
    DRAFT_STATUS_PENDING,
    DRAFT_STATUS_READY,
    DRAFT_STATUSES,
)
from web.app.models.template import Template
from web.app.models.user import User
from web.app.routes.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/drafts", tags=["drafts"])

# ── Helpers ───────────────────────────────────────────────────────────────────

_TEXT_TRUNCATE = 120


def _truncate(text: str, length: int = _TEXT_TRUNCATE) -> str:
    return text[:length] + "…" if len(text) > length else text


def _wav_duration(audio_b64: str) -> Optional[float]:
    """Compute duration in seconds from base64-encoded WAV audio."""
    try:
        wav_bytes = base64.b64decode(audio_b64)
        with wave.open(io.BytesIO(wav_bytes)) as wf:
            return round(wf.getnframes() / wf.getframerate(), 3)
    except Exception as exc:
        logger.warning("Could not compute WAV duration: %s", exc)
        return None


def _draft_to_summary(draft: Draft, character_name: Optional[str] = None) -> dict:
    """Convert Draft ORM → DraftSummary dict (no audio_b64)."""
    return {
        "id": draft.id,
        "user_id": draft.user_id,
        "character_id": draft.character_id,
        "character_name": character_name,
        "preset_name": draft.preset_name,
        "preset_type": draft.preset_type,
        "intensity": draft.intensity,
        "text": _truncate(draft.text),
        "instruct": draft.instruct,
        "language": draft.language,
        "status": draft.status,
        "audio_format": draft.audio_format,
        "duration_s": draft.duration_s,
        "error": draft.error,
        "created_at": draft.created_at.isoformat(),
        "updated_at": draft.updated_at.isoformat(),
    }


def _draft_to_full(draft: Draft, character_name: Optional[str] = None) -> dict:
    """Convert Draft ORM → full Draft dict (includes audio_b64)."""
    d = _draft_to_summary(draft, character_name)
    d["text"] = draft.text  # full text in detail view
    d["audio_b64"] = draft.audio_b64
    return d


# ── Background Task ───────────────────────────────────────────────────────────

async def _generate_draft_audio(draft_id: str) -> None:
    """Background task: call TTS relay → populate draft.audio_b64."""
    from web.app.services.tts_proxy import tts_post, TTSRelayError

    async with async_session() as db:
        try:
            # Fetch draft
            result = await db.execute(select(Draft).where(Draft.id == draft_id))
            draft = result.scalar_one_or_none()
            if draft is None:
                logger.error("Background task: draft %s not found", draft_id)
                return

            # Transition to generating
            draft.status = DRAFT_STATUS_GENERATING
            await db.commit()
            await db.refresh(draft)

            # Call TTS relay
            payload = {
                "text": draft.text,
                "instruct": draft.instruct,
                "language": draft.language,
                "format": draft.audio_format,
            }
            relay_resp = await tts_post("/api/v1/tts/voices/design", payload)

            # Extract audio from relay response
            audio_b64 = relay_resp.get("audio") or relay_resp.get("audio_b64")
            if not audio_b64:
                raise ValueError(f"TTS relay response missing 'audio' field: {list(relay_resp.keys())}")

            duration_s = _wav_duration(audio_b64)

            # Mark ready
            draft.audio_b64 = audio_b64
            draft.duration_s = duration_s
            draft.status = DRAFT_STATUS_READY
            draft.error = None
            await db.commit()
            logger.info("Draft %s ready (%.1fs)", draft_id, duration_s or 0)

        except TTSRelayError as exc:
            logger.error("Draft %s TTS error: %s", draft_id, exc.detail)
            try:
                result = await db.execute(select(Draft).where(Draft.id == draft_id))
                draft = result.scalar_one_or_none()
                if draft:
                    draft.status = DRAFT_STATUS_FAILED
                    draft.error = f"TTS relay error ({exc.status_code}): {exc.detail}"
                    await db.commit()
            except Exception:
                pass

        except Exception as exc:
            logger.error("Draft %s generation failed: %s", draft_id, exc)
            try:
                result = await db.execute(select(Draft).where(Draft.id == draft_id))
                draft = result.scalar_one_or_none()
                if draft:
                    draft.status = DRAFT_STATUS_FAILED
                    draft.error = str(exc)
                    await db.commit()
            except Exception:
                pass


# ── Schemas ───────────────────────────────────────────────────────────────────

class DraftCreate(BaseModel):
    character_id: Optional[str] = None
    preset_name: str
    preset_type: str  # "emotion" | "mode"
    intensity: Optional[str] = None  # "medium" | "intense"
    text: str
    instruct: str
    language: str = "English"


class ApproveRequest(BaseModel):
    character_id: str
    name: Optional[str] = None


class RegenerateRequest(BaseModel):
    instruct: Optional[str] = None
    text: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_draft(
    body: DraftCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new voice draft job. Returns immediately; audio generated in background."""
    # Validate preset_type
    if body.preset_type not in ("emotion", "mode"):
        raise HTTPException(status_code=400, detail="preset_type must be 'emotion' or 'mode'")
    if body.preset_type == "emotion" and body.intensity is None:
        raise HTTPException(status_code=400, detail="intensity is required for emotion presets")
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    if not body.instruct.strip():
        raise HTTPException(status_code=400, detail="instruct must not be empty")

    # Validate character_id if provided
    if body.character_id:
        result = await db.execute(
            select(Character).where(
                Character.id == body.character_id,
                Character.user_id == user.id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Character not found")

    draft = Draft(
        user_id=user.id,
        character_id=body.character_id,
        preset_name=body.preset_name,
        preset_type=body.preset_type,
        intensity=body.intensity,
        text=body.text,
        instruct=body.instruct,
        language=body.language,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)

    # Kick off background generation
    background_tasks.add_task(_generate_draft_audio, draft.id)

    return {"draft": _draft_to_summary(draft)}


@router.get("")
async def list_drafts(
    character_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all drafts for the current user (no audio_b64). Frontend polls this."""
    query = select(Draft).where(Draft.user_id == user.id)

    if character_id:
        query = query.where(Draft.character_id == character_id)

    if status_filter and status_filter != "all":
        if status_filter not in DRAFT_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status filter. Must be one of: {', '.join(sorted(DRAFT_STATUSES))}, all",
            )
        query = query.where(Draft.status == status_filter)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Paginate + order
    query = query.order_by(Draft.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    drafts = result.scalars().all()

    # Resolve character names
    char_ids = {d.character_id for d in drafts if d.character_id}
    char_map: dict[str, str] = {}
    if char_ids:
        char_result = await db.execute(
            select(Character).where(Character.id.in_(char_ids))
        )
        for char in char_result.scalars():
            char_map[char.id] = char.name

    return {
        "drafts": [_draft_to_summary(d, char_map.get(d.character_id)) for d in drafts],
        "total": total,
    }


@router.get("/{draft_id}")
async def get_draft(
    draft_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single draft including audio_b64 (for playback)."""
    result = await db.execute(
        select(Draft).where(Draft.id == draft_id, Draft.user_id == user.id)
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    character_name = None
    if draft.character_id:
        char_result = await db.execute(
            select(Character).where(Character.id == draft.character_id)
        )
        char = char_result.scalar_one_or_none()
        if char:
            character_name = char.name

    return {"draft": _draft_to_full(draft, character_name)}


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(
    draft_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Discard a draft. Cannot discard while status=generating."""
    result = await db.execute(
        select(Draft).where(Draft.id == draft_id, Draft.user_id == user.id)
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    if draft.status == DRAFT_STATUS_GENERATING:
        raise HTTPException(
            status_code=400,
            detail="Cannot discard a draft while it is generating. Wait for it to complete or fail.",
        )

    await db.delete(draft)
    await db.commit()


@router.post("/{draft_id}/approve", status_code=status.HTTP_201_CREATED)
async def approve_draft(
    draft_id: str,
    body: ApproveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve a draft — promotes it to a Character Template."""
    # Fetch draft
    result = await db.execute(
        select(Draft).where(Draft.id == draft_id, Draft.user_id == user.id)
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    if draft.status != DRAFT_STATUS_READY:
        raise HTTPException(
            status_code=400,
            detail=f"Draft must be in status=ready to approve. Current status: {draft.status}",
        )

    # Validate character
    char_result = await db.execute(
        select(Character).where(Character.id == body.character_id, Character.user_id == user.id)
    )
    character = char_result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # Build template name
    if body.name:
        template_name = body.name.strip()
    else:
        parts = [character.name, draft.preset_name]
        if draft.intensity:
            parts.append(draft.intensity)
        template_name = " – ".join(parts)

    # Create Template
    template = Template(
        user_id=user.id,
        character_id=body.character_id,
        draft_id=draft.id,
        name=template_name,
        preset_name=draft.preset_name,
        preset_type=draft.preset_type,
        intensity=draft.intensity,
        instruct=draft.instruct,
        text=draft.text,
        audio_b64=draft.audio_b64,
        audio_format=draft.audio_format,
        duration_s=draft.duration_s,
        language=draft.language,
    )
    db.add(template)

    # Mark draft approved
    draft.status = DRAFT_STATUS_APPROVED
    await db.commit()
    await db.refresh(template)

    return {
        "template": {
            "id": template.id,
            "user_id": template.user_id,
            "character_id": template.character_id,
            "character_name": character.name,
            "draft_id": template.draft_id,
            "name": template.name,
            "preset_name": template.preset_name,
            "preset_type": template.preset_type,
            "intensity": template.intensity,
            "instruct": template.instruct,
            "text": _truncate(template.text),
            "audio_format": template.audio_format,
            "duration_s": template.duration_s,
            "language": template.language,
            "created_at": template.created_at.isoformat(),
        }
    }


@router.post("/{draft_id}/regenerate", status_code=status.HTTP_201_CREATED)
async def regenerate_draft(
    draft_id: str,
    body: RegenerateRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate: create a new draft from an existing one (old draft remains)."""
    result = await db.execute(
        select(Draft).where(Draft.id == draft_id, Draft.user_id == user.id)
    )
    original = result.scalar_one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail="Original draft not found")

    new_draft = Draft(
        user_id=user.id,
        character_id=original.character_id,
        preset_name=original.preset_name,
        preset_type=original.preset_type,
        intensity=original.intensity,
        text=body.text if body.text is not None else original.text,
        instruct=body.instruct if body.instruct is not None else original.instruct,
        language=original.language,
    )
    db.add(new_draft)
    await db.commit()
    await db.refresh(new_draft)

    background_tasks.add_task(_generate_draft_audio, new_draft.id)

    return {"draft": _draft_to_summary(new_draft)}
