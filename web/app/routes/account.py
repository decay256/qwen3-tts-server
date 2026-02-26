"""Account management routes — change password, update email, delete account."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from web.app.core.database import get_db
from web.app.core.security import hash_password, verify_password
from web.app.models.character import Character
from web.app.models.user import User
from web.app.routes.deps import get_current_user

router = APIRouter(prefix="/api/v1/account", tags=["account"])


class AccountResponse(BaseModel):
    id: str
    email: str
    is_verified: bool
    created_at: str

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UpdateEmailRequest(BaseModel):
    email: EmailStr
    password: str  # require password to change email


class DeleteAccountRequest(BaseModel):
    password: str


@router.get("", response_model=AccountResponse)
async def get_account(user: User = Depends(get_current_user)):
    """Get current account info."""
    return AccountResponse(
        id=user.id,
        email=user.email,
        is_verified=user.is_verified,
        created_at=str(user.created_at),
    )


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change password. Requires current password."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"message": "Password changed successfully"}


@router.post("/change-email")
async def change_email(
    body: UpdateEmailRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change email. Requires password confirmation."""
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect")

    # Check email not taken
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already in use")

    user.email = body.email.lower()
    user.is_verified = False  # require re-verification
    await db.commit()
    return {"message": "Email updated. Please verify your new email."}


@router.post("/delete")
async def delete_account(
    body: DeleteAccountRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete account and all associated data. Requires password."""
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect")

    # Delete user's characters first
    result = await db.execute(select(Character).where(Character.user_id == user.id))
    for char in result.scalars().all():
        await db.delete(char)

    await db.delete(user)
    await db.commit()
    return {"message": "Account deleted"}
