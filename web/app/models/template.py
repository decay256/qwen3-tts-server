"""Template model — an approved voice template for a character."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from web.app.core.database import Base


class Template(Base):
    """A character voice template created by approving a Draft.

    Templates represent the canonical voice identity for a character at a given
    preset + intensity combination.

    Audio is stored as base64 WAV in audio_b64 (copied from the approved Draft).
    List endpoints MUST NOT include audio_b64.

    NOTE: No GPU clone-prompt is created on approve at Sprint 4.
    Clone-prompt creation is deferred to Sprint 5.
    """

    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    draft_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("drafts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    preset_name: Mapped[str] = mapped_column(String(128), nullable=False)
    preset_type: Mapped[str] = mapped_column(String(16), nullable=False)  # "emotion" | "mode"
    intensity: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    instruct: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    audio_b64: Mapped[str] = mapped_column(Text, nullable=False)  # base64 WAV
    audio_format: Mapped[str] = mapped_column(String(8), nullable=False, default="wav")
    duration_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    language: Mapped[str] = mapped_column(String(64), nullable=False, default="English")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<Template {self.id[:8]} name={self.name!r}>"
