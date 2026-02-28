"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Voice Studio configuration.

    All settings can be overridden via environment variables
    (prefixed with nothing — flat namespace for simplicity).
    """

    # App
    app_name: str = "Voice Studio"
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]  # Vite dev server

    # Database
    database_url: str = "postgresql+asyncpg://voicestudio:voicestudio@localhost:5432/voicestudio"

    # JWT
    jwt_secret: str = "CHANGE-ME-IN-PRODUCTION"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 60
    jwt_refresh_expire_days: int = 30

    # TTS Relay
    tts_relay_url: str = "http://localhost:9800"
    tts_relay_api_key: str = ""

    # Email (Resend)
    resend_api_key: str = ""
    email_from: str = "onboarding@resend.dev"  # TODO: switch to noreply@dk-eigenvektor.de after domain verification

    # LLM (configurable provider)
    llm_provider: str = "openai"  # "openai" or "anthropic"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_model: str = "gpt-4o-mini"  # or "claude-sonnet-4-6"

    model_config = {"env_file": [".env", "web/.env"], "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
