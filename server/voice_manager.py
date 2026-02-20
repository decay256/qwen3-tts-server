"""Voice catalog manager — stores and retrieves voice profiles."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Optional

from dataclasses import dataclass

from server.tts_engine import TTSEngine

logger = logging.getLogger(__name__)


@dataclass
class VoiceProfile:
    """A voice profile for TTS generation."""
    voice_id: str
    name: str
    voice_type: str  # "cloned", "designed", "builtin"
    reference_audio: Optional[str] = None
    description: Optional[str] = None

# Default audiobook voice cast
DEFAULT_VOICE_CAST: dict[str, dict] = {
    "Narrator": {
        "description": "Deep, warm male narrator voice with gravitas and clarity",
    },
    "Maya": {
        "description": "Young woman, warm and expressive, slight vulnerability",
    },
    "Elena": {
        "description": "Mature woman, confident and authoritative, Eastern European accent",
    },
    "Chen": {
        "description": "Middle-aged man, calm and analytical, slight Chinese accent",
    },
    "Raj": {
        "description": "Young man, enthusiastic and energetic, Indian accent",
    },
    "Kim": {
        "description": "Young woman, sharp and professional, Korean-American",
    },
}


class VoiceManager:
    """Manages voice profiles: cloned, designed, and preset voices.

    Persists voice catalog to disk as JSON alongside any reference audio files.
    """

    def __init__(self, voices_dir: str | Path, engine: Optional[TTSEngine] = None) -> None:
        """Initialize the voice manager.

        Args:
            voices_dir: Directory to store voice data and catalog.
            engine: Optional TTS engine for creating voices on the fly.
        """
        self.voices_dir = Path(voices_dir)
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        self.engine = engine

        self._catalog_path = self.voices_dir / "catalog.json"
        self._voices: dict[str, VoiceProfile] = {}

        self._load_catalog()

    def _load_catalog(self) -> None:
        """Load voice catalog from disk."""
        if not self._catalog_path.exists():
            logger.info("No voice catalog found, starting fresh")
            return

        try:
            data = json.loads(self._catalog_path.read_text(encoding="utf-8"))
            for entry in data:
                profile = VoiceProfile(
                    voice_id=entry["voice_id"],
                    name=entry["name"],
                    voice_type=entry["voice_type"],
                    reference_audio=entry.get("reference_audio"),
                    description=entry.get("description"),
                )
                self._voices[profile.voice_id] = profile
            logger.info("Loaded %d voices from catalog", len(self._voices))
        except Exception:
            logger.exception("Failed to load voice catalog")

    def _save_catalog(self) -> None:
        """Persist voice catalog to disk."""
        data = []
        for v in self._voices.values():
            entry = {
                "voice_id": v.voice_id,
                "name": v.name,
                "voice_type": v.voice_type,
            }
            if v.reference_audio:
                entry["reference_audio"] = v.reference_audio
            if v.description:
                entry["description"] = v.description
            data.append(entry)

        self._catalog_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def list_voices(self) -> list[dict]:
        """List all available voices.

        Returns:
            List of voice info dicts.
        """
        return [
            {
                "voice_id": v.voice_id,
                "name": v.name,
                "type": v.voice_type,
                "description": v.description,
            }
            for v in self._voices.values()
        ]

    def get_voice(self, voice_id: str) -> Optional[VoiceProfile]:
        """Get a voice profile by ID.

        Also supports lookup by name (case-insensitive).

        Args:
            voice_id: Voice ID or name.

        Returns:
            VoiceProfile or None.
        """
        # Direct ID lookup
        if voice_id in self._voices:
            return self._voices[voice_id]

        # Name lookup
        for v in self._voices.values():
            if v.name.lower() == voice_id.lower():
                return v

        return None

    def clone_voice(self, reference_audio_path: str, name: str) -> VoiceProfile:
        """Clone a voice from reference audio.

        Args:
            reference_audio_path: Path to the reference audio file.
            name: Human-readable name for this voice.

        Returns:
            The new VoiceProfile.
        """
        voice_id = f"cloned_{uuid.uuid4().hex[:12]}"

        # Copy reference audio to voices directory
        src = Path(reference_audio_path)
        if not src.exists():
            raise FileNotFoundError(f"Reference audio not found: {reference_audio_path}")

        dest = self.voices_dir / f"{voice_id}{src.suffix}"
        shutil.copy2(src, dest)

        profile = VoiceProfile(
            voice_id=voice_id,
            name=name,
            voice_type="cloned",
            reference_audio=str(dest),
        )
        self._voices[voice_id] = profile
        self._save_catalog()

        logger.info("Cloned voice '%s' (id=%s) from %s", name, voice_id, src.name)
        return profile

    def clone_voice_from_bytes(self, audio_data: bytes, name: str, suffix: str = ".wav") -> VoiceProfile:
        """Clone a voice from audio bytes (e.g., uploaded file).

        Args:
            audio_data: Raw audio file bytes.
            name: Human-readable name.
            suffix: File extension.

        Returns:
            The new VoiceProfile.
        """
        voice_id = f"cloned_{uuid.uuid4().hex[:12]}"
        dest = self.voices_dir / f"{voice_id}{suffix}"
        dest.write_bytes(audio_data)

        profile = VoiceProfile(
            voice_id=voice_id,
            name=name,
            voice_type="cloned",
            reference_audio=str(dest),
        )
        self._voices[voice_id] = profile
        self._save_catalog()

        logger.info("Cloned voice '%s' (id=%s) from uploaded audio", name, voice_id)
        return profile

    def design_voice(self, description: str, name: Optional[str] = None) -> VoiceProfile:
        """Design a voice from a text description.

        Args:
            description: Natural language description of the voice.
            name: Optional name; auto-generated if not provided.

        Returns:
            The new VoiceProfile.
        """
        voice_id = f"designed_{uuid.uuid4().hex[:12]}"
        if name is None:
            # Generate name from first few words of description
            words = description.split()[:3]
            name = "_".join(words).strip(".,;:")

        profile = VoiceProfile(
            voice_id=voice_id,
            name=name,
            voice_type="designed",
            description=description,
        )
        self._voices[voice_id] = profile
        self._save_catalog()

        logger.info("Designed voice '%s' (id=%s): %s", name, voice_id, description[:80])
        return profile

    def initialize_default_cast(self, cast_config: Optional[dict] = None) -> None:
        """Initialize the default audiobook voice cast if not already present.

        Args:
            cast_config: Voice cast config dict. Uses DEFAULT_VOICE_CAST if None.
        """
        cast = cast_config or DEFAULT_VOICE_CAST

        for name, info in cast.items():
            existing = self.get_voice(name)
            if existing:
                logger.debug("Voice '%s' already exists, skipping", name)
                continue

            description = info.get("description", f"Default voice for {name}")
            voice_type = info.get("type", "designed")

            if voice_type == "designed":
                self.design_voice(description, name=name)
            elif voice_type == "cloned" and "reference_audio" in info:
                self.clone_voice(info["reference_audio"], name)

        logger.info("Default voice cast initialized (%d voices total)", len(self._voices))

    def delete_voice(self, voice_id: str) -> bool:
        """Delete a voice profile.

        Args:
            voice_id: The voice ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        profile = self._voices.pop(voice_id, None)
        if profile is None:
            return False

        # Remove reference audio file if it exists
        if profile.reference_audio:
            ref_path = Path(profile.reference_audio)
            if ref_path.exists():
                ref_path.unlink()

        self._save_catalog()
        logger.info("Deleted voice '%s' (id=%s)", profile.name, voice_id)
        return True
