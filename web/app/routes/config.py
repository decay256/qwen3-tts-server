"""Configuration routes — view and update runtime settings."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from web.app.core.config import settings
from web.app.models.user import User
from web.app.routes.deps import get_current_user

router = APIRouter(prefix="/api/v1/config", tags=["config"])


class ConfigResponse(BaseModel):
    tts_relay_url: str
    llm_provider: str
    llm_model: str
    email_from: str
    has_resend_key: bool
    has_openai_key: bool
    has_anthropic_key: bool


class ConfigUpdate(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None


@router.get("", response_model=ConfigResponse)
async def get_config(user: User = Depends(get_current_user)):
    """Get current server configuration (secrets masked)."""
    return ConfigResponse(
        tts_relay_url=settings.tts_relay_url,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        email_from=settings.email_from,
        has_resend_key=bool(settings.resend_api_key),
        has_openai_key=bool(settings.openai_api_key),
        has_anthropic_key=bool(settings.anthropic_api_key),
    )


@router.patch("", response_model=ConfigResponse)
async def update_config(body: ConfigUpdate, user: User = Depends(get_current_user)):
    """Update runtime configuration (LLM provider/model).

    Note: These changes are in-memory only and reset on server restart.
    For persistent changes, update the .env file.
    """
    if body.llm_provider is not None:
        if body.llm_provider not in ("openai", "anthropic"):
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Provider must be 'openai' or 'anthropic'")
        settings.llm_provider = body.llm_provider
    if body.llm_model is not None:
        settings.llm_model = body.llm_model

    return ConfigResponse(
        tts_relay_url=settings.tts_relay_url,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        email_from=settings.email_from,
        has_resend_key=bool(settings.resend_api_key),
        has_openai_key=bool(settings.openai_api_key),
        has_anthropic_key=bool(settings.anthropic_api_key),
    )
