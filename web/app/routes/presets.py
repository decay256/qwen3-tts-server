"""Preset routes — serve emotion/mode presets and support custom CRUD.

Built-in presets come from server/emotion_presets.py (read-only).
Custom presets are stored in SQLite and can override built-ins by name.
GET /api/v1/presets merges both; custom takes precedence over built-in.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from web.app.core.database import get_db
from web.app.models.preset import CustomPreset
from web.app.models.user import User
from web.app.routes.deps import get_current_user

router = APIRouter(prefix="/api/v1/presets", tags=["presets"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class EmotionPresetCreate(BaseModel):
    name: str
    instruct_medium: str
    instruct_intense: str
    ref_text_medium: str
    ref_text_intense: str
    tags: list[str] = []

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


class EmotionPresetUpdate(BaseModel):
    instruct_medium: Optional[str] = None
    instruct_intense: Optional[str] = None
    ref_text_medium: Optional[str] = None
    ref_text_intense: Optional[str] = None
    tags: Optional[list[str]] = None


class ModePresetCreate(BaseModel):
    name: str
    instruct: str
    ref_text: str
    tags: list[str] = []

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


class ModePresetUpdate(BaseModel):
    instruct: Optional[str] = None
    ref_text: Optional[str] = None
    tags: Optional[list[str]] = None


# ── Serialisation helpers ────────────────────────────────────────────────────


def _builtin_presets() -> dict:
    """Load and serialise built-in presets from emotion_presets.py."""
    from server.emotion_presets import (
        EMOTION_ORDER, EMOTION_PRESETS,
        MODE_ORDER, MODE_PRESETS,
    )

    emotions: dict[str, dict] = {}
    for name in EMOTION_ORDER:
        p = EMOTION_PRESETS[name]
        emotions[name] = {
            "name": p.name,
            "type": "emotion",
            "instruct_medium": p.instruct_medium,
            "instruct_intense": p.instruct_intense,
            "ref_text_medium": p.ref_text_medium,
            "ref_text_intense": p.ref_text_intense,
            "tags": p.tags,
            "is_builtin": True,
        }

    modes: dict[str, dict] = {}
    for name in MODE_ORDER:
        p = MODE_PRESETS[name]
        modes[name] = {
            "name": p.name,
            "type": "mode",
            "instruct": p.instruct,
            "ref_text": p.ref_text,
            "tags": p.tags,
            "is_builtin": True,
        }

    return {"emotions": emotions, "modes": modes}


def _custom_to_dict(p: CustomPreset) -> dict:
    """Convert a CustomPreset ORM object to a response dict."""
    base = {
        "name": p.name,
        "type": p.type,
        "tags": p.tags or [],
        "is_builtin": False,
    }
    if p.type == "emotion":
        base.update({
            "instruct_medium": p.instruct_medium or "",
            "instruct_intense": p.instruct_intense or "",
            "ref_text_medium": p.ref_text_medium or "",
            "ref_text_intense": p.ref_text_intense or "",
        })
    else:
        base.update({
            "instruct": p.instruct or "",
            "ref_text": p.ref_text or "",
        })
    return base


# ── GET /api/v1/presets ──────────────────────────────────────────────────────


@router.get("")
async def get_presets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return merged preset list: built-ins + user customs (custom overrides built-in by name)."""
    builtin = _builtin_presets()

    # Load all custom presets for this user
    result = await db.execute(
        select(CustomPreset).where(CustomPreset.user_id == user.id)
    )
    customs = result.scalars().all()

    emotions_map = dict(builtin["emotions"])  # name → dict
    modes_map = dict(builtin["modes"])

    for cp in customs:
        d = _custom_to_dict(cp)
        if cp.type == "emotion":
            emotions_map[cp.name] = d
        else:
            modes_map[cp.name] = d

    # Preserve built-in order, then append custom-only entries alphabetically
    from server.emotion_presets import EMOTION_ORDER, MODE_ORDER

    ordered_emotions = []
    seen_emotions = set()
    for name in EMOTION_ORDER:
        if name in emotions_map:
            ordered_emotions.append(emotions_map[name])
            seen_emotions.add(name)
    for name in sorted(emotions_map.keys()):
        if name not in seen_emotions:
            ordered_emotions.append(emotions_map[name])

    ordered_modes = []
    seen_modes = set()
    for name in MODE_ORDER:
        if name in modes_map:
            ordered_modes.append(modes_map[name])
            seen_modes.add(name)
    for name in sorted(modes_map.keys()):
        if name not in seen_modes:
            ordered_modes.append(modes_map[name])

    return {"emotions": ordered_emotions, "modes": ordered_modes}


# ── POST /api/v1/presets/emotions ────────────────────────────────────────────


@router.post("/emotions", status_code=201)
async def create_emotion_preset(
    body: EmotionPresetCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a custom emotion preset. Returns 409 if name already exists for this user."""
    result = await db.execute(
        select(CustomPreset).where(
            and_(
                CustomPreset.user_id == user.id,
                CustomPreset.type == "emotion",
                CustomPreset.name == body.name,
            )
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Emotion preset '{body.name}' already exists",
        )

    preset = CustomPreset(
        user_id=user.id,
        type="emotion",
        name=body.name,
        instruct_medium=body.instruct_medium,
        instruct_intense=body.instruct_intense,
        ref_text_medium=body.ref_text_medium,
        ref_text_intense=body.ref_text_intense,
        tags=body.tags,
    )
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return _custom_to_dict(preset)


# ── PATCH /api/v1/presets/emotions/{name} ────────────────────────────────────


@router.patch("/emotions/{name}")
async def update_emotion_preset(
    name: str,
    body: EmotionPresetUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit a custom emotion preset. Built-ins are read-only — editing creates a custom override."""
    result = await db.execute(
        select(CustomPreset).where(
            and_(
                CustomPreset.user_id == user.id,
                CustomPreset.type == "emotion",
                CustomPreset.name == name,
            )
        )
    )
    preset = result.scalar_one_or_none()

    if preset is None:
        # Check if it's a built-in — if so, create a custom override
        try:
            from server.emotion_presets import EMOTION_PRESETS
            builtin = EMOTION_PRESETS.get(name)
        except ImportError:
            builtin = None

        if builtin is None:
            raise HTTPException(status_code=404, detail=f"Emotion preset '{name}' not found")

        # Create an override record seeded from built-in values
        preset = CustomPreset(
            user_id=user.id,
            type="emotion",
            name=name,
            instruct_medium=builtin.instruct_medium,
            instruct_intense=builtin.instruct_intense,
            ref_text_medium=builtin.ref_text_medium,
            ref_text_intense=builtin.ref_text_intense,
            tags=list(builtin.tags),
        )
        db.add(preset)

    # Apply updates
    if body.instruct_medium is not None:
        preset.instruct_medium = body.instruct_medium
    if body.instruct_intense is not None:
        preset.instruct_intense = body.instruct_intense
    if body.ref_text_medium is not None:
        preset.ref_text_medium = body.ref_text_medium
    if body.ref_text_intense is not None:
        preset.ref_text_intense = body.ref_text_intense
    if body.tags is not None:
        preset.tags = body.tags

    await db.commit()
    await db.refresh(preset)
    return _custom_to_dict(preset)


# ── DELETE /api/v1/presets/emotions/{name} ───────────────────────────────────


@router.delete("/emotions/{name}", status_code=204)
async def delete_emotion_preset(
    name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a custom emotion preset. Cannot delete built-ins."""
    result = await db.execute(
        select(CustomPreset).where(
            and_(
                CustomPreset.user_id == user.id,
                CustomPreset.type == "emotion",
                CustomPreset.name == name,
            )
        )
    )
    preset = result.scalar_one_or_none()
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Custom emotion preset '{name}' not found")

    await db.execute(
        delete(CustomPreset).where(
            and_(
                CustomPreset.user_id == user.id,
                CustomPreset.type == "emotion",
                CustomPreset.name == name,
            )
        )
    )
    await db.commit()


# ── POST /api/v1/presets/modes ───────────────────────────────────────────────


@router.post("/modes", status_code=201)
async def create_mode_preset(
    body: ModePresetCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a custom mode preset. Returns 409 if name already exists for this user."""
    result = await db.execute(
        select(CustomPreset).where(
            and_(
                CustomPreset.user_id == user.id,
                CustomPreset.type == "mode",
                CustomPreset.name == body.name,
            )
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Mode preset '{body.name}' already exists",
        )

    preset = CustomPreset(
        user_id=user.id,
        type="mode",
        name=body.name,
        instruct=body.instruct,
        ref_text=body.ref_text,
        tags=body.tags,
    )
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return _custom_to_dict(preset)


# ── PATCH /api/v1/presets/modes/{name} ──────────────────────────────────────


@router.patch("/modes/{name}")
async def update_mode_preset(
    name: str,
    body: ModePresetUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit a custom mode preset. Built-ins are read-only — editing creates a custom override."""
    result = await db.execute(
        select(CustomPreset).where(
            and_(
                CustomPreset.user_id == user.id,
                CustomPreset.type == "mode",
                CustomPreset.name == name,
            )
        )
    )
    preset = result.scalar_one_or_none()

    if preset is None:
        try:
            from server.emotion_presets import MODE_PRESETS
            builtin = MODE_PRESETS.get(name)
        except ImportError:
            builtin = None

        if builtin is None:
            raise HTTPException(status_code=404, detail=f"Mode preset '{name}' not found")

        preset = CustomPreset(
            user_id=user.id,
            type="mode",
            name=name,
            instruct=builtin.instruct,
            ref_text=builtin.ref_text,
            tags=list(builtin.tags),
        )
        db.add(preset)

    if body.instruct is not None:
        preset.instruct = body.instruct
    if body.ref_text is not None:
        preset.ref_text = body.ref_text
    if body.tags is not None:
        preset.tags = body.tags

    await db.commit()
    await db.refresh(preset)
    return _custom_to_dict(preset)


# ── DELETE /api/v1/presets/modes/{name} ─────────────────────────────────────


@router.delete("/modes/{name}", status_code=204)
async def delete_mode_preset(
    name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a custom mode preset. Cannot delete built-ins."""
    result = await db.execute(
        select(CustomPreset).where(
            and_(
                CustomPreset.user_id == user.id,
                CustomPreset.type == "mode",
                CustomPreset.name == name,
            )
        )
    )
    preset = result.scalar_one_or_none()
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Custom mode preset '{name}' not found")

    await db.execute(
        delete(CustomPreset).where(
            and_(
                CustomPreset.user_id == user.id,
                CustomPreset.type == "mode",
                CustomPreset.name == name,
            )
        )
    )
    await db.commit()
