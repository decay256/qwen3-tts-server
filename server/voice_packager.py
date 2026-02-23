"""Voice packaging system — export/import voices as self-contained .voicepkg.zip files."""

from __future__ import annotations

import base64
import json
import logging
import shutil
import tempfile
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Union

import librosa
import soundfile as sf

from server.voice_manager import VoiceManager, VoiceProfile

logger = logging.getLogger(__name__)


class VoicePackager:
    """Handles export/import of voice packages."""

    def __init__(self, voice_manager: VoiceManager) -> None:
        """Initialize the packager.
        
        Args:
            voice_manager: Voice manager instance.
        """
        self.voice_manager = voice_manager

    def export_package(self, voice_id: str, output_path: Union[str, Path, None] = None) -> Path:
        """Export a voice as a .voicepkg.zip file.
        
        Args:
            voice_id: Voice ID to export.
            output_path: Optional output path. If None, creates in temp directory.
            
        Returns:
            Path to the created package file.
            
        Raises:
            ValueError: If voice not found or cannot be packaged.
        """
        voice = self.voice_manager.get_voice(voice_id)
        if not voice:
            raise ValueError(f"Voice not found: {voice_id}")

        # Generate output path if not provided
        if output_path is None:
            temp_dir = Path(tempfile.mkdtemp())
            output_path = temp_dir / f"{voice_id}.voicepkg.zip"
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Exporting voice '{voice.name}' (id={voice_id}) to {output_path}")

        # Create the package
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add metadata
            meta = self._build_meta_json(voice)
            zf.writestr("meta.json", json.dumps(meta, indent=2, ensure_ascii=False))

            # Add reference audio if it exists
            if voice.reference_audio and Path(voice.reference_audio).exists():
                ref_path = Path(voice.reference_audio)
                zf.write(ref_path, "ref.wav")

                # Add transcript file if ref_text exists
                if voice.ref_text:
                    zf.writestr("ref_transcript.txt", voice.ref_text)

            # Add sample directory (currently empty, but structure is there)
            zf.writestr("samples/.gitkeep", "")

        logger.info(f"Voice package created: {output_path} ({output_path.stat().st_size} bytes)")
        return output_path

    def import_package(self, package_data: Union[str, Path, bytes]) -> VoiceProfile:
        """Import a voice package.
        
        Args:
            package_data: Path to zip file, or raw zip bytes.
            
        Returns:
            The imported VoiceProfile.
            
        Raises:
            ValueError: If package is invalid or voice already exists.
        """
        if isinstance(package_data, (str, Path)):
            # File path
            zip_path = Path(package_data)
            if not zip_path.exists():
                raise ValueError(f"Package file not found: {zip_path}")
            logger.info(f"Importing voice package from file: {zip_path}")
            with open(zip_path, "rb") as f:
                zip_data = f.read()
        else:
            # Raw bytes
            zip_data = package_data
            logger.info(f"Importing voice package from bytes ({len(zip_data)} bytes)")

        # Extract and validate the package
        with zipfile.ZipFile(BytesIO(zip_data), "r") as zf:
            # Read metadata
            try:
                meta_content = zf.read("meta.json").decode("utf-8")
                meta = json.loads(meta_content)
            except KeyError:
                raise ValueError("Invalid package: missing meta.json")
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid package: corrupted meta.json: {e}")

            # Validate metadata
            self._validate_meta(meta)
            voice_id = meta["voice_id"]

            # Check if voice already exists
            existing = self.voice_manager.get_voice(voice_id)
            if existing:
                raise ValueError(f"Voice already exists: {voice_id}")

            # Create voice directory
            if meta["voice_type"] == "cloned":
                voice_dir = self.voice_manager.voices_dir / f"{voice_id}"
            else:
                voice_dir = self.voice_manager.voices_dir / f"{voice_id}"
            voice_dir.mkdir(parents=True, exist_ok=True)

            # Extract reference audio if present
            ref_audio_path = None
            if "ref.wav" in zf.namelist():
                ref_audio_path = voice_dir / "ref.wav"
                with open(ref_audio_path, "wb") as f:
                    f.write(zf.read("ref.wav"))

            # Extract transcript if present
            ref_text = None
            if "ref_transcript.txt" in zf.namelist():
                ref_text = zf.read("ref_transcript.txt").decode("utf-8")

            # Create VoiceProfile
            profile = VoiceProfile(
                voice_id=meta["voice_id"],
                name=meta["name"],
                voice_type=meta["voice_type"],
                description=meta.get("description"),
                reference_audio=str(ref_audio_path) if ref_audio_path else None,
                ref_text=ref_text or meta.get("ref_text"),
                design_description=meta.get("design_description"),
                design_language=meta.get("design_language"),
                source=meta.get("source"),
                casting_notes=meta.get("casting_notes"),
                created_at=meta.get("created_at"),
                display_name=meta.get("display_name"),
            )

            # Register with voice manager
            self.voice_manager._voices[voice_id] = profile
            self.voice_manager._save_catalog()

            logger.info(f"Successfully imported voice '{profile.name}' (id={voice_id})")
            return profile

    def export_all(self, output_dir: Union[str, Path]) -> list[Path]:
        """Export all voices as packages.
        
        Args:
            output_dir: Directory to save packages.
            
        Returns:
            List of created package paths.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        packages = []
        for voice_id in self.voice_manager._voices:
            try:
                package_path = output_dir / f"{voice_id}.voicepkg.zip"
                self.export_package(voice_id, package_path)
                packages.append(package_path)
            except Exception as e:
                logger.error(f"Failed to export voice {voice_id}: {e}")

        logger.info(f"Exported {len(packages)} voice packages to {output_dir}")
        return packages

    def _build_meta_json(self, voice: VoiceProfile) -> dict:
        """Build meta.json content for a voice.
        
        Args:
            voice: Voice profile to package.
            
        Returns:
            Metadata dict.
        """
        meta = {
            "format_version": 1,
            "voice_id": voice.voice_id,
            "name": voice.name,
            "display_name": voice.display_name or voice.name,
            "voice_type": voice.voice_type,
            "description": voice.description or "",
            "package_created_at": datetime.now().isoformat() + "Z",
        }

        # Add voice-type specific fields
        if voice.voice_type == "cloned":
            if voice.ref_text:
                meta["ref_text"] = voice.ref_text

            # Add audio metadata if reference audio exists
            if voice.reference_audio and Path(voice.reference_audio).exists():
                try:
                    y, sr = librosa.load(voice.reference_audio, sr=None)
                    meta["ref_duration_s"] = round(len(y) / sr, 1)
                    meta["ref_sample_rate"] = int(sr)
                except Exception as e:
                    logger.warning(f"Could not read audio metadata: {e}")
                    meta["ref_duration_s"] = 0.0
                    meta["ref_sample_rate"] = 24000

        elif voice.voice_type == "designed":
            if voice.design_description:
                meta["design_description"] = voice.design_description
            if voice.design_language:
                meta["design_language"] = voice.design_language

        # Add optional fields
        if voice.source:
            meta["source"] = voice.source
        if voice.casting_notes:
            meta["casting_notes"] = voice.casting_notes
        if voice.created_at:
            meta["created_at"] = voice.created_at

        # Add model info (hardcoded for now)
        meta["model_used"] = "Qwen3-TTS-12Hz-1.7B-Base"

        return meta

    def _validate_meta(self, meta: dict) -> None:
        """Validate metadata from package.
        
        Args:
            meta: Metadata dict to validate.
            
        Raises:
            ValueError: If metadata is invalid.
        """
        required_fields = ["format_version", "voice_id", "name", "voice_type"]
        for field in required_fields:
            if field not in meta:
                raise ValueError(f"Invalid package: missing required field '{field}'")

        if meta["format_version"] != 1:
            raise ValueError(f"Unsupported package format version: {meta['format_version']}")

        if meta["voice_type"] not in ["cloned", "designed", "builtin"]:
            raise ValueError(f"Invalid voice_type: {meta['voice_type']}")