"""Configuration management for Qwen3-TTS server."""

import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / ".env")


def _get_or_generate_token() -> str:
    """Get auth token from env or generate and save one."""
    token = os.getenv("AUTH_TOKEN", "").strip()
    if token:
        return token
    token = secrets.token_urlsafe(48)
    env_path = _project_root / ".env"
    if env_path.exists():
        content = env_path.read_text()
        content = content.replace("AUTH_TOKEN=", f"AUTH_TOKEN={token}", 1)
        env_path.write_text(content)
    else:
        env_path.write_text(f"AUTH_TOKEN={token}\n")
    return token


# Auth
AUTH_TOKEN: str = _get_or_generate_token()

# Bridge
BRIDGE_URL: str = os.getenv("BRIDGE_URL", "")
BRIDGE_HTTP_PORT: int = int(os.getenv("BRIDGE_HTTP_PORT", "8766"))
BRIDGE_WS_PORT: int = int(os.getenv("BRIDGE_WS_PORT", "8765"))

# Models
ENABLED_MODELS: list[str] = [
    m.strip() for m in os.getenv("ENABLED_MODELS", "voice_design,base").split(",")
]
MODEL_CACHE_DIR: str | None = os.getenv("MODEL_CACHE_DIR") or None
CUDA_DEVICE: str = os.getenv("CUDA_DEVICE", "cuda:0")

# Limits
RATE_LIMIT: int = int(os.getenv("RATE_LIMIT", "30"))
MAX_TEXT_LENGTH: int = int(os.getenv("MAX_TEXT_LENGTH", "5000"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# Voices
VOICES_DIR: Path = Path(os.getenv("VOICES_DIR", str(_project_root / "voices")))
VOICES_DIR.mkdir(parents=True, exist_ok=True)

# Model name mapping
MODEL_HF_IDS: dict[str, str] = {
    "voice_design": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "custom_voice": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "base": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "custom_voice_small": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
    "base_small": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
}
