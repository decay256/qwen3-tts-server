"""Character management routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from web.app.core.database import get_db
from web.app.models.character import Character
from web.app.models.user import User
from web.app.routes.deps import get_current_user

router = APIRouter(prefix="/api/v1/characters", tags=["characters"])


# ── Schemas ─────────────────────────────────────────────────────────


class CharacterCreate(BaseModel):
    name: str
    base_description: str


class CharacterUpdate(BaseModel):
    name: str | None = None
    base_description: str | None = None


class CharacterResponse(BaseModel):
    id: str
    name: str
    base_description: str
    created_at: str | datetime
    updated_at: str | datetime

    model_config = {"from_attributes": True}


# ── Routes ──────────────────────────────────────────────────────────


@router.post("", response_model=CharacterResponse, status_code=201)
async def create_character(
    body: CharacterCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new character voice definition."""
    character = Character(
        user_id=user.id,
        name=body.name,
        base_description=body.base_description,
    )
    db.add(character)
    await db.commit()
    await db.refresh(character)
    return character


@router.get("", response_model=list[CharacterResponse])
async def list_characters(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all characters owned by the current user."""
    result = await db.execute(
        select(Character).where(Character.user_id == user.id).order_by(Character.name)
    )
    return result.scalars().all()


@router.get("/{character_id}", response_model=CharacterResponse)
async def get_character(
    character_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a character by ID."""
    result = await db.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user.id)
    )
    character = result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    return character


@router.patch("/{character_id}", response_model=CharacterResponse)
async def update_character(
    character_id: str,
    body: CharacterUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a character's name or base description."""
    result = await db.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user.id)
    )
    character = result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    if body.name is not None:
        character.name = body.name
    if body.base_description is not None:
        character.base_description = body.base_description

    await db.commit()
    await db.refresh(character)
    return character


@router.delete("/{character_id}", status_code=204)
async def delete_character(
    character_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a character."""
    result = await db.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user.id)
    )
    character = result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    await db.delete(character)
    await db.commit()
