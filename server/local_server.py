"""Local GPU server — runs on the machine with the GPU.

Loads Qwen3-TTS models, connects to the remote relay via WebSocket tunnel,
and handles TTS requests.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import yaml

from server.tts_engine import TTSEngine
from server.tunnel import MessageType, TunnelClient, TunnelMessage
from server.voice_manager import VoiceManager, VoiceProfile

logger = logging.getLogger(__name__)


def load_config(config_path: str = "config.yaml") -> dict:
    """Load and validate configuration from YAML file.

    Args:
        config_path: Path to config file.

    Returns:
        Configuration dict.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If required fields are missing.
    """
    path = Path(config_path)
    if not path.exists():
        # Try config.example.yaml as fallback
        example = Path("config.example.yaml")
        if example.exists():
            raise FileNotFoundError(
                f"Config file '{config_path}' not found. "
                f"Copy config.example.yaml to config.yaml and fill in your values."
            )
        raise FileNotFoundError(f"Config file '{config_path}' not found.")

    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Validate required fields
    if not config.get("api_key") or config["api_key"] == "CHANGE_ME":
        raise ValueError("api_key must be set in config.yaml (run: python -m scripts.generate_keys)")

    remote = config.get("remote", {})
    if not remote.get("host"):
        raise ValueError("remote.host must be set in config.yaml")

    return config


class LocalServer:
    """The local GPU TTS server.

    Loads models, manages voices, and processes requests from the tunnel.
    """

    def __init__(self, config: dict) -> None:
        """Initialize the local server.

        Args:
            config: Parsed configuration dict.
        """
        self.config = config
        self.start_time = time.time()

        local_cfg = config.get("local", {})

        # Initialize TTS engine
        self.engine = TTSEngine()

        # Initialize voice manager
        voices_dir = local_cfg.get("voices_dir", "./voices")
        self.voice_manager = VoiceManager(voices_dir, engine=self.engine)

        # Build tunnel URL
        remote = config["remote"]
        scheme = "wss" if remote.get("tls", False) else "ws"
        host = remote["host"]
        port = remote.get("port", 9800)
        self.tunnel_url = f"{scheme}://{host}:{port}/ws/tunnel"

        # Tunnel client
        self.tunnel = TunnelClient(
            remote_url=self.tunnel_url,
            api_key=config["api_key"],
            request_handler=self._handle_request,
            tls=remote.get("tls", False),
            ca_cert=remote.get("ca_cert"),
        )

    async def start(self) -> None:
        """Start the local server: load models, init voices, connect tunnel."""
        logger.info("=" * 60)
        logger.info("Qwen3-TTS Local Server starting up")
        logger.info("=" * 60)

        # Load models
        logger.info("Loading TTS models...")
        try:
            self.engine.load_models()
        except Exception:
            logger.exception("Failed to load models")
            logger.warning("Continuing without models (API will return errors for TTS requests)")

        # Initialize default voice cast
        cast_config = self.config.get("voice_cast")
        self.voice_manager.initialize_default_cast(cast_config)
        logger.info("Voices ready: %d available", len(self.voice_manager.list_voices()))

        # Connect to remote relay
        logger.info("Connecting to remote relay at %s", self.tunnel_url)
        await self.tunnel.start()

    async def stop(self) -> None:
        """Stop the server and clean up."""
        logger.info("Shutting down local server...")
        await self.tunnel.stop()
        # Models are freed when process exits
        logger.info("Server stopped")

    async def _handle_request(self, request: TunnelMessage) -> TunnelMessage:
        """Route incoming tunnel requests to the appropriate handler.

        Args:
            request: Incoming request message.

        Returns:
            Response message.
        """
        path = request.path or ""
        method = (request.method or "GET").upper()

        logger.info("Handling %s %s", method, path)

        try:
            if path == "/api/v1/status" and method == "GET":
                return await self._handle_status(request)
            elif path == "/api/v1/tts/voices" and method == "GET":
                return await self._handle_list_voices(request)
            elif path == "/api/v1/tts/synthesize" and method == "POST":
                return await self._handle_synthesize(request)
            elif path == "/api/v1/tts/clone" and method == "POST":
                return await self._handle_clone(request)
            elif path == "/api/v1/tts/design" and method == "POST":
                return await self._handle_design(request)
            else:
                return TunnelMessage(
                    type=MessageType.RESPONSE,
                    status_code=404,
                    body=json.dumps({"error": f"Not found: {method} {path}"}),
                )
        except Exception as e:
            logger.exception("Error handling request %s %s", method, path)
            return TunnelMessage(
                type=MessageType.RESPONSE,
                status_code=500,
                body=json.dumps({"error": str(e)}),
            )

    async def _handle_status(self, request: TunnelMessage) -> TunnelMessage:
        """Handle GET /api/v1/status."""
        gpu_info = self.engine.get_health()
        uptime = time.time() - self.start_time

        status = {
            "status": "ok",
            "gpu": gpu_info.get("gpu_name", "N/A"),
            "vram_used_gb": gpu_info.get("vram_used_gb", 0),
            "vram_total_gb": gpu_info.get("vram_total_gb", 0),
            "models_loaded": gpu_info.get("loaded_models", []),
            "voices_count": len(self.voice_manager.list_voices()),
            "uptime_seconds": round(uptime, 1),
            "engine_ready": self.engine.is_loaded,
        }

        return TunnelMessage(
            type=MessageType.RESPONSE,
            body=json.dumps(status),
            headers={"Content-Type": "application/json"},
        )

    async def _handle_list_voices(self, request: TunnelMessage) -> TunnelMessage:
        """Handle GET /api/v1/tts/voices."""
        voices = self.voice_manager.list_voices()
        return TunnelMessage(
            type=MessageType.RESPONSE,
            body=json.dumps({"voices": voices}),
            headers={"Content-Type": "application/json"},
        )

    async def _handle_synthesize(self, request: TunnelMessage) -> TunnelMessage:
        """Handle POST /api/v1/tts/synthesize."""
        if not request.body:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                status_code=400,
                body=json.dumps({"error": "Missing request body"}),
            )

        data = json.loads(request.body)
        text = data.get("text")
        voice_id = data.get("voice_id")
        instructions = data.get("instructions")
        output_format = data.get("format", "mp3")

        if not text:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                status_code=400,
                body=json.dumps({"error": "Missing 'text' field"}),
            )
        if not voice_id:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                status_code=400,
                body=json.dumps({"error": "Missing 'voice_id' field"}),
            )

        voice = self.voice_manager.get_voice(voice_id)
        if not voice:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                status_code=404,
                body=json.dumps({"error": f"Voice not found: {voice_id}"}),
            )

        if not self.engine.is_loaded:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                status_code=503,
                body=json.dumps({"error": "TTS models not loaded"}),
            )

        # Run synthesis in thread pool to avoid blocking
        loop = asyncio.get_event_loop()

        from .tts_engine import wav_to_format
        import functools

        if voice.voice_type == "designed":
            func = functools.partial(
                self.engine.generate_voice_design,
                text=text, description=voice.description or "", language="Auto",
            )
        elif voice.voice_type == "cloned" and voice.reference_audio:
            with open(voice.reference_audio, "rb") as f:
                ref_b64 = base64.b64encode(f.read()).decode()
            func = functools.partial(
                self.engine.generate_voice_clone,
                text=text, ref_audio_b64=ref_b64, language="Auto",
            )
        else:
            func = functools.partial(
                self.engine.generate_custom_voice,
                text=text, speaker=voice.name, instruct=instructions or "", language="Auto",
            )

        wav_data, sr = await loop.run_in_executor(None, func)
        audio_bytes = wav_to_format(wav_data, sr, output_format)
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

        response_data = {
            "audio": audio_b64,
            "format": output_format,
            "sample_rate": sr,
            "voice_id": voice_id,
        }

        return TunnelMessage(
            type=MessageType.RESPONSE,
            body=json.dumps(response_data),
            body_binary=True,
            headers={"Content-Type": "application/json"},
        )

    async def _handle_clone(self, request: TunnelMessage) -> TunnelMessage:
        """Handle POST /api/v1/tts/clone."""
        if not request.body:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                status_code=400,
                body=json.dumps({"error": "Missing request body"}),
            )

        data = json.loads(request.body)
        voice_name = data.get("voice_name")
        audio_b64 = data.get("reference_audio")

        if not voice_name or not audio_b64:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                status_code=400,
                body=json.dumps({"error": "Missing 'voice_name' or 'reference_audio'"}),
            )

        audio_bytes = base64.b64decode(audio_b64)
        profile = self.voice_manager.clone_voice_from_bytes(audio_bytes, voice_name)

        return TunnelMessage(
            type=MessageType.RESPONSE,
            body=json.dumps({
                "voice_id": profile.voice_id,
                "name": profile.name,
                "type": profile.voice_type,
            }),
            headers={"Content-Type": "application/json"},
        )

    async def _handle_design(self, request: TunnelMessage) -> TunnelMessage:
        """Handle POST /api/v1/tts/design."""
        if not request.body:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                status_code=400,
                body=json.dumps({"error": "Missing request body"}),
            )

        data = json.loads(request.body)
        description = data.get("description")
        name = data.get("name")

        if not description:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                status_code=400,
                body=json.dumps({"error": "Missing 'description' field"}),
            )

        profile = self.voice_manager.design_voice(description, name=name)

        return TunnelMessage(
            type=MessageType.RESPONSE,
            body=json.dumps({
                "voice_id": profile.voice_id,
                "name": profile.name,
                "type": profile.voice_type,
                "description": profile.description,
            }),
            headers={"Content-Type": "application/json"},
        )


def setup_logging(config: dict) -> None:
    """Configure logging from config.

    Args:
        config: Configuration dict.
    """
    log_config = config.get("logging", {})
    level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
    log_file = log_config.get("file")

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def main() -> None:
    """Entry point for the local GPU server."""
    config_path = os.environ.get("QWEN3_TTS_CONFIG", "config.yaml")

    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    setup_logging(config)
    server = LocalServer(config)

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        asyncio.run(server.stop())


if __name__ == "__main__":
    main()
