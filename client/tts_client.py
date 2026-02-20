"""Python client library for the Qwen3-TTS remote relay API."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class TTSResponse:
    """Response from a TTS synthesis request."""

    audio_data: bytes
    format: str
    duration_seconds: float
    sample_rate: int
    voice_id: str

    def save(self, path: Union[str, Path]) -> None:
        """Save audio to file.

        Args:
            path: Output file path.
        """
        Path(path).write_bytes(self.audio_data)
        logger.info("Saved %d bytes to %s", len(self.audio_data), path)


@dataclass
class VoiceInfo:
    """Information about an available voice."""

    voice_id: str
    name: str
    voice_type: str  # "cloned", "designed", "preset"
    description: Optional[str] = None


class TTSClient:
    """Async client for the Qwen3-TTS remote relay API.

    Usage:
        async with TTSClient("http://104.248.27.154:9800", "your-api-key") as client:
            result = await client.synthesize("Hello world", voice_id="Narrator")
            result.save("output.mp3")
    """

    def __init__(self, base_url: str, api_key: str, timeout: float = 300) -> None:
        """Initialize the TTS client.

        Args:
            base_url: Base URL of the remote relay (e.g. http://104.248.27.154:9800).
            api_key: API key for authentication.
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> TTSClient:
        self._session = aiohttp.ClientSession(
            timeout=self.timeout,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._session:
            await self._session.close()

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("Client not initialized. Use 'async with TTSClient(...)' context.")
        return self._session

    async def status(self) -> dict:
        """Get server status.

        Returns:
            Status dict with relay and local server info.
        """
        async with self.session.get(f"{self.base_url}/api/v1/status") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def list_voices(self) -> list[VoiceInfo]:
        """List available voices.

        Returns:
            List of VoiceInfo objects.
        """
        async with self.session.get(f"{self.base_url}/api/v1/tts/voices") as resp:
            resp.raise_for_status()
            data = await resp.json()
            return [
                VoiceInfo(
                    voice_id=v["voice_id"],
                    name=v["name"],
                    voice_type=v["type"],
                    description=v.get("description"),
                )
                for v in data.get("voices", [])
            ]

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        instructions: Optional[str] = None,
        format: str = "mp3",
    ) -> TTSResponse:
        """Synthesize text to speech.

        Args:
            text: Text to speak.
            voice_id: Voice ID or name.
            instructions: Optional speaking instructions.
            format: Audio format ('mp3' or 'wav').

        Returns:
            TTSResponse with audio data.
        """
        payload = {
            "text": text,
            "voice_id": voice_id,
            "format": format,
        }
        if instructions:
            payload["instructions"] = instructions

        async with self.session.post(
            f"{self.base_url}/api/v1/tts/synthesize", json=payload
        ) as resp:
            resp.raise_for_status()

            audio_data = await resp.read()
            return TTSResponse(
                audio_data=audio_data,
                format=resp.headers.get("Content-Type", f"audio/{format}").split("/")[-1],
                duration_seconds=float(resp.headers.get("X-Duration-Seconds", "0")),
                sample_rate=int(resp.headers.get("X-Sample-Rate", "24000")),
                voice_id=resp.headers.get("X-Voice-ID", voice_id),
            )

    async def clone_voice(
        self, reference_audio: Union[str, Path, bytes], voice_name: str
    ) -> VoiceInfo:
        """Clone a voice from reference audio.

        Args:
            reference_audio: Path to audio file or raw bytes.
            voice_name: Name for the cloned voice.

        Returns:
            VoiceInfo for the new voice.
        """
        if isinstance(reference_audio, (str, Path)):
            audio_data = Path(reference_audio).read_bytes()
        else:
            audio_data = reference_audio

        form = aiohttp.FormData()
        form.add_field("voice_name", voice_name)
        form.add_field(
            "reference_audio",
            io.BytesIO(audio_data),
            filename="reference.wav",
            content_type="audio/wav",
        )

        async with self.session.post(
            f"{self.base_url}/api/v1/tts/clone", data=form
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return VoiceInfo(
                voice_id=data["voice_id"],
                name=data["name"],
                voice_type=data["type"],
            )

    async def design_voice(
        self, description: str, name: Optional[str] = None
    ) -> VoiceInfo:
        """Design a voice from a text description.

        Args:
            description: Natural language description of the voice.
            name: Optional name for the voice.

        Returns:
            VoiceInfo for the new voice.
        """
        payload: dict = {"description": description}
        if name:
            payload["name"] = name

        async with self.session.post(
            f"{self.base_url}/api/v1/tts/design", json=payload
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return VoiceInfo(
                voice_id=data["voice_id"],
                name=data["name"],
                voice_type=data["type"],
                description=data.get("description"),
            )
