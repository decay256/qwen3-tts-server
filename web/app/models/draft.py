"""Draft model — a voice generation job in the draft queue."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from web.app.core.database import Base

# Status literals
DRAFT_STATUS_PENDING = "pending"
DRAFT_STATUS_GENERATING = "generating"
DRAFT_STATUS_READY = "ready"
DRAFT_STATUS_FAILED = "failed"
DRAFT_STATUS_APPROVED = "approved"

DRAFT_STATUSES = {
    DRAFT_STATUS_PENDING,
    DRAFT_STATUS_GENERATING,
    DRAFT_STATUS_READY,
    DRAFT_STATUS_FAILED,
    DRAFT_STATUS_APPROVED,
}


class Draft(Base):
    """A voice generation job.

    Lifecycle: pending → generating → ready | failed
    Approved drafts: ready → approved (Template created)

    Audio is stored as base64 WAV in audio_b64 (populated when status=ready).
    List endpoints MUST NOT include audio_b64 — it is large (~50-200KB base64).
    """

    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    character_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    preset_name: Mapped[str] = mapped_column(String(128), nullable=False)
    preset_type: Mapped[str] = mapped_column(String(16), nullable=False)  # "emotion" | "mode"
    intensity: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # "medium" | "intense"
    text: Mapped[str] = mapped_column(Text, nullable=False)
    instruct: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False, default="English")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DRAFT_STATUS_PENDING, index=True)
    audio_b64: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # base64 WAV
    audio_format: Mapped[str] = mapped_column(String(8), nullable=False, default="wav")
    duration_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<Draft {self.id[:8]} status={self.status}>"
