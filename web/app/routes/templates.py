"""Template routes — approved voice templates per character.

GET    /api/v1/templates                       — list all templates (no audio_b64)
GET    /api/v1/templates/{template_id}         — full template with audio_b64
PATCH  /api/v1/templates/{template_id}         — rename template
DELETE /api/v1/templates/{template_id}         — delete template
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from web.app.core.database import get_db
from web.app.models.character import Character
from web.app.models.template import Template
from web.app.models.user import User
from web.app.routes.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])

_TEXT_TRUNCATE = 120


def _truncate(text: str, length: int = _TEXT_TRUNCATE) -> str:
    return text[:length] + "…" if len(text) > length else text


def _template_to_summary(t: Template, character_name: Optional[str] = None) -> dict:
    """Convert Template ORM → TemplateSummary dict (no audio_b64)."""
    return {
        "id": t.id,
        "user_id": t.user_id,
        "character_id": t.character_id,
        "character_name": character_name,
        "draft_id": t.draft_id,
        "name": t.name,
        "preset_name": t.preset_name,
        "preset_type": t.preset_type,
        "intensity": t.intensity,
        "instruct": t.instruct,
        "text": _truncate(t.text),
        "audio_format": t.audio_format,
        "duration_s": t.duration_s,
        "language": t.language,
        "created_at": t.created_at.isoformat(),
    }


def _template_to_full(t: Template, character_name: Optional[str] = None) -> dict:
    """Convert Template ORM → full Template dict (includes audio_b64)."""
    d = _template_to_summary(t, character_name)
    d["text"] = t.text  # full text in detail view
    d["audio_b64"] = t.audio_b64
    return d


class TemplateRename(BaseModel):
    name: str


@router.get("")
async def list_templates(
    character_id: Optional[str] = Query(None),
    preset_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all templates for the current user (no audio_b64)."""
    query = select(Template).where(Template.user_id == user.id)

    if character_id:
        query = query.where(Template.character_id == character_id)

    if preset_type:
        if preset_type not in ("emotion", "mode"):
            raise HTTPException(status_code=400, detail="preset_type must be 'emotion' or 'mode'")
        query = query.where(Template.preset_type == preset_type)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    query = query.order_by(Template.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    templates = result.scalars().all()

    # Resolve character names
    char_ids = {t.character_id for t in templates}
    char_map: dict[str, str] = {}
    if char_ids:
        char_result = await db.execute(
            select(Character).where(Character.id.in_(char_ids))
        )
        for char in char_result.scalars():
            char_map[char.id] = char.name

    return {
        "templates": [_template_to_summary(t, char_map.get(t.character_id)) for t in templates],
        "total": total,
    }


@router.get("/{template_id}")
async def get_template(
    template_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single template including audio_b64."""
    result = await db.execute(
        select(Template).where(Template.id == template_id, Template.user_id == user.id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    character_name = None
    char_result = await db.execute(
        select(Character).where(Character.id == template.character_id)
    )
    char = char_result.scalar_one_or_none()
    if char:
        character_name = char.name

    return {"template": _template_to_full(template, character_name)}


@router.patch("/{template_id}")
async def rename_template(
    template_id: str,
    body: TemplateRename,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename a template."""
    result = await db.execute(
        select(Template).where(Template.id == template_id, Template.user_id == user.id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Template name must not be empty")

    template.name = name
    await db.commit()
    await db.refresh(template)

    character_name = None
    char_result = await db.execute(
        select(Character).where(Character.id == template.character_id)
    )
    char = char_result.scalar_one_or_none()
    if char:
        character_name = char.name

    return {"template": _template_to_summary(template, character_name)}


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a template. Source Draft is NOT deleted."""
    result = await db.execute(
        select(Template).where(Template.id == template_id, Template.user_id == user.id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    await db.delete(template)
    await db.commit()
