"""Preset routes — serve emotion/mode presets for the frontend editor."""

from fastapi import APIRouter, Depends

from web.app.models.user import User
from web.app.routes.deps import get_current_user

router = APIRouter(prefix="/api/v1/presets", tags=["presets"])


def _serialize_presets():
    """Import and serialize all presets."""
    from server.emotion_presets import (
        EMOTION_PRESETS, MODE_PRESETS, EMOTION_ORDER, MODE_ORDER,
    )

    emotions = []
    for name in EMOTION_ORDER:
        p = EMOTION_PRESETS[name]
        emotions.append({
            "name": p.name,
            "type": "emotion",
            "instruct_medium": p.instruct_medium,
            "instruct_intense": p.instruct_intense,
            "ref_text_medium": p.ref_text_medium,
            "ref_text_intense": p.ref_text_intense,
            "tags": p.tags,
        })

    modes = []
    for name in MODE_ORDER:
        p = MODE_PRESETS[name]
        modes.append({
            "name": p.name,
            "type": "mode",
            "instruct": p.instruct,
            "ref_text": p.ref_text,
            "tags": p.tags,
        })

    return {"emotions": emotions, "modes": modes}


@router.get("")
async def get_presets(user: User = Depends(get_current_user)):
    """Get all emotion and mode presets for the voice editor."""
    return _serialize_presets()
