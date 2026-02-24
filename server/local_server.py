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
from server.tunnel import MessageType, TunnelMessage
from server.tunnel_v2 import EnhancedTunnelClient
from server.voice_manager import VoiceManager, VoiceProfile
from server.voice_packager import VoicePackager
from server.prompt_store import PromptStore

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
        
        # Initialize voice packager
        self.voice_packager = VoicePackager(self.voice_manager)

        # Initialize clone prompt store
        prompts_dir = local_cfg.get("prompts_dir", "./voice-prompts")
        self.prompt_store = PromptStore(prompts_dir)

        # Build tunnel URL
        remote = config["remote"]
        scheme = "wss" if remote.get("tls", False) else "ws"
        host = remote["host"]
        port = remote.get("port", 9800)
        self.tunnel_url = f"{scheme}://{host}:{port}/ws/tunnel"

        # Enhanced tunnel client with robust connection management
        self.tunnel = EnhancedTunnelClient(
            remote_url=self.tunnel_url,
            api_key=config["api_key"],
            on_message=self._handle_tunnel_message,
            ca_cert=remote.get("ca_cert") if remote.get("tls", False) else None,
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

        # Initialize voices from config (if provided)
        cast_config = self.config.get("voice_cast")
        if cast_config:
            self.voice_manager.initialize_voices_from_config(cast_config)
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

    async def _handle_tunnel_message(self, message: TunnelMessage) -> None:
        """Handle incoming tunnel messages (callback-based).
        
        Args:
            message: Incoming message from tunnel.
        """
        logger.debug("Received tunnel message: type=%s, path=%s, method=%s, request_id=%s", 
                    message.type, message.path, message.method, message.request_id)
        
        try:
            if message.type == MessageType.REQUEST:
                logger.debug("Processing request: %s %s", message.method, message.path)
                # Process request and send response
                response = await self._handle_request(message)
                logger.debug("Sending response: status=%s, body_size=%s, request_id=%s", 
                           response.status_code, len(response.body or ""), response.request_id)
                await self.tunnel.send_message(response)
                logger.debug("Response sent successfully")
            # Other message types (heartbeat, etc.) are handled automatically by enhanced client
            
        except Exception as e:
            logger.error("Error handling tunnel message: %s", e, exc_info=True)
            # Send error response if this was a request
            if message.type == MessageType.REQUEST:
                error_response = TunnelMessage(
                    type=MessageType.RESPONSE,
                    request_id=message.request_id,
                    status_code=500,
                    body=json.dumps({"error": f"Internal server error: {str(e)}"})
                )
                try:
                    await self.tunnel.send_message(error_response)
                    logger.debug("Error response sent")
                except Exception as send_error:
                    logger.error("Failed to send error response: %s", send_error)

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
            elif path.startswith("/api/v1/tts/voices/") and method == "DELETE":
                return await self._handle_delete_voice(request)
            elif path.startswith("/api/v1/tts/voices/") and path.endswith("/package") and method == "GET":
                return await self._handle_export_package(request)
            elif path == "/api/v1/tts/voices/import" and method == "POST":
                return await self._handle_import_package(request)
            elif path == "/api/v1/tts/voices/sync" and method == "POST":
                return await self._handle_sync_packages(request)
            # Clone prompt endpoints
            elif path == "/api/v1/voices/design" and method == "POST":
                return await self._handle_voice_design(request)
            elif path == "/api/v1/voices/clone-prompt" and method == "POST":
                return await self._handle_create_clone_prompt(request)
            elif path == "/api/v1/voices/prompts" and method == "GET":
                return await self._handle_list_prompts(request)
            elif path.startswith("/api/v1/voices/prompts/") and method == "DELETE":
                return await self._handle_delete_prompt(request)
            elif path == "/api/v1/tts/clone-prompt" and method == "POST":
                return await self._handle_synthesize_with_prompt(request)
            # Batch endpoints
            elif path == "/api/v1/voices/design/batch" and method == "POST":
                return await self._handle_batch_design(request)
            elif path == "/api/v1/voices/clone-prompt/batch" and method == "POST":
                return await self._handle_batch_clone_prompt(request)
            # Casting
            elif path == "/api/v1/voices/cast" and method == "POST":
                return await self._handle_cast_voice(request)
            elif path == "/api/v1/voices/emotions" and method == "GET":
                return await self._handle_list_emotions(request)
            # Audio processing
            elif path == "/api/v1/audio/normalize" and method == "POST":
                return await self._handle_normalize(request)
            else:
                return TunnelMessage(
                    type=MessageType.RESPONSE,
                request_id=request.request_id,
                    status_code=404,
                    body=json.dumps({"error": f"Not found: {method} {path}"}),
                )
        except Exception as e:
            logger.exception("Error handling request %s %s", method, path)
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=500,
                body=json.dumps({"error": str(e)}),
            )

    async def _handle_status(self, request: TunnelMessage) -> TunnelMessage:
        """Handle GET /api/v1/status - includes enhanced tunnel health."""
        gpu_info = self.engine.get_health()
        uptime = time.time() - self.start_time
        tunnel_status = self.tunnel.get_status()

        status = {
            "status": "ok",
            "gpu": gpu_info.get("gpu_name", "N/A"),
            "vram_used_gb": gpu_info.get("vram_used_gb", 0),
            "vram_total_gb": gpu_info.get("vram_total_gb", 0),
            "models_loaded": gpu_info.get("loaded_models", []),
            "voices_count": len(self.voice_manager.list_voices()),
            "prompts_count": len(self.prompt_store.list_prompts()),
            "uptime_seconds": round(uptime, 1),
            "engine_ready": self.engine.is_loaded,
            # Enhanced tunnel health information
            "tunnel": {
                "connected": tunnel_status["connected"],
                "state": tunnel_status["state"],
                "connection_count": tunnel_status["connection_count"],
                "success_rate": round(tunnel_status["health"]["success_rate"], 3),
                "consecutive_failures": tunnel_status["health"]["consecutive_failures"],
                "circuit_breaker_active": tunnel_status["circuit_breaker"]["active"]
            }
        }

        return TunnelMessage(
            type=MessageType.RESPONSE,
            request_id=request.request_id,
            body=json.dumps(status),
            headers={"Content-Type": "application/json"},
        )

    async def _handle_list_voices(self, request: TunnelMessage) -> TunnelMessage:
        """Handle GET /api/v1/tts/voices."""
        voices = self.voice_manager.list_voices()
        return TunnelMessage(
            type=MessageType.RESPONSE,
                request_id=request.request_id,
            body=json.dumps({"voices": voices}),
            headers={"Content-Type": "application/json"},
        )

    async def _handle_delete_voice(self, request: TunnelMessage) -> TunnelMessage:
        """Handle DELETE /api/v1/tts/voices/{voice_id}."""
        path = request.path or ""
        voice_id = path.rsplit("/", 1)[-1]

        if not voice_id:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=400,
                body=json.dumps({"error": "voice_id required"}),
                headers={"Content-Type": "application/json"},
            )

        deleted = self.voice_manager.delete_voice(voice_id)
        if deleted:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                body=json.dumps({"deleted": voice_id}),
                headers={"Content-Type": "application/json"},
            )
        else:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=404,
                body=json.dumps({"error": f"Voice not found: {voice_id}"}),
                headers={"Content-Type": "application/json"},
            )

    async def _handle_synthesize(self, request: TunnelMessage) -> TunnelMessage:
        """Handle POST /api/v1/tts/synthesize.

        Supports two modes:
        - voice_id: look up by ID or name, use design/clone/builtin as appropriate
        - voice_name: shortcut for clone-mode — look up saved voice by name
        """
        logger.debug("=== SYNTHESIZE START ===")
        if not request.body:
            logger.debug("Missing request body")
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=400,
                body=json.dumps({"error": "Missing request body"}),
            )

        data = json.loads(request.body)
        logger.debug("Request data: %s", {k: v for k, v in data.items() if k != 'text'})
        logger.debug("Text length: %d characters", len(data.get('text', '')))
        text = data.get("text")
        voice_id = data.get("voice_id")
        voice_name = data.get("voice_name")
        instructions = data.get("instructions")
        output_format = data.get("format", "mp3")

        if not text:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=400,
                body=json.dumps({"error": "Missing 'text' field"}),
            )

        # Resolve voice: voice_name takes precedence (clone mode)
        voice = None
        lookup_key = voice_name or voice_id
        if not lookup_key:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=400,
                body=json.dumps({"error": "Missing 'voice_id' or 'voice_name' field"}),
            )

        voice = self.voice_manager.get_voice(lookup_key)
        if not voice:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=404,
                body=json.dumps({"error": f"Voice not found: {lookup_key}"}),
            )

        if not self.engine.is_loaded:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=503,
                body=json.dumps({"error": "TTS models not loaded"}),
            )

        # Run synthesis in thread pool to avoid blocking
        loop = asyncio.get_event_loop()

        from .tts_engine import wav_to_format
        import functools

        if voice.voice_type == "cloned" and voice.reference_audio:
            # Clone mode — consistent voice from saved reference audio
            with open(voice.reference_audio, "rb") as f:
                ref_b64 = base64.b64encode(f.read()).decode()
            # ref_text must be the transcript of the REFERENCE audio, not the target text.
            # qwen-tts REQUIRES non-empty ref_text in ICL mode (x_vector_only_mode=False).
            # If no ref_text stored, fall back to x_vector_only_mode (lower quality but works).
            ref_text = voice.ref_text or ""
            if ref_text:
                func = functools.partial(
                    self.engine.generate_voice_clone,
                    text=text, ref_audio_b64=ref_b64, ref_text=ref_text, language="Auto",
                )
            else:
                logger.warning("Voice %s has no ref_text — using x_vector_only_mode (lower quality)", voice.name)
                func = functools.partial(
                    self.engine.generate_voice_clone,
                    text=text, ref_audio_b64=ref_b64, ref_text="", language="Auto",
                    x_vector_only_mode=True,
                )
        elif voice.voice_type == "designed":
            # Design mode — stochastic, different each time
            description = voice.description or ""
            if instructions:
                description = f"{description}. {instructions}" if description else instructions
            func = functools.partial(
                self.engine.generate_voice_design,
                text=text, description=description, language="Auto",
            )
        else:
            # Builtin CustomVoice mode
            func = functools.partial(
                self.engine.generate_custom_voice,
                text=text, speaker=voice.name, instruct=instructions or "", language="Auto",
            )

        logger.debug("Starting voice generation...")
        wav_data, sr = await loop.run_in_executor(None, func)
        logger.debug("Voice generation complete! wav shape: %s, sr: %d", wav_data.shape, sr)
        
        logger.debug("Converting to format: %s", output_format)
        audio_bytes = wav_to_format(wav_data, sr, output_format)
        logger.debug("Format conversion complete! Size: %d bytes", len(audio_bytes))
        
        logger.debug("Encoding to base64...")
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        logger.debug("Encoding complete! Base64 size: %d", len(audio_b64))

        response_data = {
            "audio": audio_b64,
            "format": output_format,
            "sample_rate": sr,
            "voice_id": voice.voice_id,
        }

        logger.debug("=== SYNTHESIZE COMPLETE ===")
        return TunnelMessage(
            type=MessageType.RESPONSE,
            request_id=request.request_id,
            body=json.dumps(response_data),
            body_binary=True,
            headers={"Content-Type": "application/json"},
        )

    async def _handle_clone(self, request: TunnelMessage) -> TunnelMessage:
        """Handle POST /api/v1/tts/clone."""
        if not request.body:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=400,
                body=json.dumps({"error": "Missing request body"}),
            )

        data = json.loads(request.body)
        voice_name = data.get("voice_name")
        audio_b64 = data.get("reference_audio")

        if not voice_name or not audio_b64:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=400,
                body=json.dumps({"error": "Missing 'voice_name' or 'reference_audio'"}),
            )

        audio_bytes = base64.b64decode(audio_b64)
        profile = self.voice_manager.clone_voice_from_bytes(audio_bytes, voice_name)

        # Auto-sync the new voice to relay
        asyncio.create_task(self._auto_sync_voice(profile.voice_id))

        return TunnelMessage(
            type=MessageType.RESPONSE,
                request_id=request.request_id,
            body=json.dumps({
                "voice_id": profile.voice_id,
                "name": profile.name,
                "type": profile.voice_type,
            }),
            headers={"Content-Type": "application/json"},
        )

    async def _handle_design(self, request: TunnelMessage) -> TunnelMessage:
        """Handle POST /api/v1/tts/design.

        Generates speech with a designed voice from a text description.
        Returns the audio so the caller can audition it and optionally
        save it as a clone reference via /clone.

        Required fields: text, description
        Optional: language (default "English"), format (default "wav"), name
        """
        if not request.body:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=400,
                body=json.dumps({"error": "Missing request body"}),
            )

        data = json.loads(request.body)
        text = data.get("text")
        description = data.get("description")
        language = data.get("language", "English")
        output_format = data.get("format", "wav")

        if not text:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=400,
                body=json.dumps({"error": "Missing 'text' field"}),
            )
        if not description:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=400,
                body=json.dumps({"error": "Missing 'description' field"}),
            )

        if not self.engine.is_loaded:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=503,
                body=json.dumps({"error": "TTS models not loaded"}),
            )

        loop = asyncio.get_event_loop()
        from .tts_engine import wav_to_format
        import functools

        func = functools.partial(
            self.engine.generate_voice_design,
            text=text, description=description, language=language,
        )
        wav_data, sr = await loop.run_in_executor(None, func)
        audio_bytes = wav_to_format(wav_data, sr, output_format)
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

        return TunnelMessage(
            type=MessageType.RESPONSE,
                request_id=request.request_id,
            body=json.dumps({
                "audio": audio_b64,
                "format": output_format,
                "sample_rate": sr,
                "description": description,
            }),
            body_binary=True,
            headers={"Content-Type": "application/json"},
        )

    async def _handle_export_package(self, request: TunnelMessage) -> TunnelMessage:
        """Handle GET /api/v1/tts/voices/{voice_id}/package."""
        path = request.path or ""
        voice_id = path.split("/")[-2]  # Extract voice_id from path like /api/v1/tts/voices/{voice_id}/package

        if not voice_id:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=400,
                body=json.dumps({"error": "voice_id required"}),
                headers={"Content-Type": "application/json"},
            )

        try:
            package_path = self.voice_packager.export_package(voice_id)
            with open(package_path, "rb") as f:
                package_data = f.read()
            
            # Clean up temp file
            package_path.unlink()
            
            # Return as base64 for tunnel transport
            package_b64 = base64.b64encode(package_data).decode("ascii")

            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                body=json.dumps({
                    "package": package_b64,
                    "filename": f"{voice_id}.voicepkg.zip",
                }),
                body_binary=True,
                headers={"Content-Type": "application/json"},
            )

        except ValueError as e:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=404,
                body=json.dumps({"error": str(e)}),
                headers={"Content-Type": "application/json"},
            )
        except Exception as e:
            logger.exception("Error exporting voice package")
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=500,
                body=json.dumps({"error": f"Export failed: {str(e)}"}),
                headers={"Content-Type": "application/json"},
            )

    async def _handle_import_package(self, request: TunnelMessage) -> TunnelMessage:
        """Handle POST /api/v1/tts/voices/import."""
        if not request.body:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=400,
                body=json.dumps({"error": "Missing request body"}),
                headers={"Content-Type": "application/json"},
            )

        try:
            data = json.loads(request.body)
            package_b64 = data.get("package")

            if not package_b64:
                return TunnelMessage(
                    type=MessageType.RESPONSE,
                    request_id=request.request_id,
                    status_code=400,
                    body=json.dumps({"error": "Missing 'package' field (base64 encoded zip)"}),
                    headers={"Content-Type": "application/json"},
                )

            # Decode package data
            package_data = base64.b64decode(package_b64)
            
            # Import the package
            profile = self.voice_packager.import_package(package_data)

            # Send auto-sync notification to relay (fire and forget)
            asyncio.create_task(self._auto_sync_voice(profile.voice_id))

            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                body=json.dumps({
                    "voice_id": profile.voice_id,
                    "name": profile.name,
                    "type": profile.voice_type,
                    "imported": True,
                }),
                headers={"Content-Type": "application/json"},
            )

        except ValueError as e:
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=400,
                body=json.dumps({"error": str(e)}),
                headers={"Content-Type": "application/json"},
            )
        except Exception as e:
            logger.exception("Error importing voice package")
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=500,
                body=json.dumps({"error": f"Import failed: {str(e)}"}),
                headers={"Content-Type": "application/json"},
            )

    async def _handle_sync_packages(self, request: TunnelMessage) -> TunnelMessage:
        """Handle POST /api/v1/tts/voices/sync - export all voices and send to relay."""
        try:
            # Export all voice packages to temporary directory
            import tempfile
            with tempfile.TemporaryDirectory() as temp_dir:
                packages = self.voice_packager.export_all(temp_dir)
                
                # Read all packages and encode as base64
                package_data = {}
                for package_path in packages:
                    voice_id = package_path.stem.replace(".voicepkg", "")
                    with open(package_path, "rb") as f:
                        package_bytes = f.read()
                    package_data[voice_id] = base64.b64encode(package_bytes).decode("ascii")

                return TunnelMessage(
                    type=MessageType.RESPONSE,
                    request_id=request.request_id,
                    body=json.dumps({
                        "synced_voices": len(package_data),
                        "packages": package_data,
                    }),
                    body_binary=True,
                    headers={"Content-Type": "application/json"},
                )

        except Exception as e:
            logger.exception("Error syncing voice packages")
            return TunnelMessage(
                type=MessageType.RESPONSE,
                request_id=request.request_id,
                status_code=500,
                body=json.dumps({"error": f"Sync failed: {str(e)}"}),
                headers={"Content-Type": "application/json"},
            )

    # ── Clone Prompt Endpoints ─────────────────────────────────────

    def _require_base_model(self, request: TunnelMessage) -> TunnelMessage | None:
        """Check if base model is loaded. Returns error response if not, None if OK."""
        if not self.engine.is_loaded:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=503, body=json.dumps({"error": "TTS engine not loaded"}),
            )
        has_base = "base" in self.engine._models or "base_small" in self.engine._models
        if not has_base:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=503,
                body=json.dumps({"error": "Base model not loaded. Enable it via ENABLED_MODELS=base,voice_design"}),
            )
        return None

    async def _handle_voice_design(self, request: TunnelMessage) -> TunnelMessage:
        """POST /api/v1/voices/design — generate reference clip via VoiceDesign."""
        if not self.engine.is_loaded:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=503, body=json.dumps({"error": "TTS engine not loaded"}),
            )

        body = json.loads(request.body) if request.body else {}
        text = body.get("text")
        instruct = body.get("instruct")
        language = body.get("language", "English")
        fmt = body.get("format", "wav")

        if not text or not instruct:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=400, body=json.dumps({"error": "Missing 'text' and 'instruct'"}),
            )

        import functools
        from server.tts_engine import wav_to_format

        loop = asyncio.get_event_loop()
        func = functools.partial(self.engine.generate_voice_design, text=text, description=instruct, language=language)
        wav, sr = await loop.run_in_executor(None, func)

        audio_bytes = wav_to_format(wav, sr, fmt)
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

        return TunnelMessage(
            type=MessageType.RESPONSE, request_id=request.request_id,
            body=json.dumps({"audio": audio_b64, "format": fmt, "sample_rate": sr, "duration_s": round(len(wav) / sr, 2)}),
            headers={"Content-Type": "application/json"},
        )

    async def _handle_create_clone_prompt(self, request: TunnelMessage) -> TunnelMessage:
        """POST /api/v1/voices/clone-prompt — create persistent clone prompt."""
        err = self._require_base_model(request)
        if err:
            return err

        body = json.loads(request.body) if request.body else {}
        name = body.get("name")
        ref_audio_b64 = body.get("ref_audio_base64")
        ref_text = body.get("ref_text", "")
        tags = body.get("tags", [])

        if not name:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=400, body=json.dumps({"error": "Missing 'name'"}),
            )
        if not ref_audio_b64:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=400, body=json.dumps({"error": "Missing 'ref_audio_base64'"}),
            )

        import functools

        loop = asyncio.get_event_loop()

        # Calculate ref audio duration
        import io, soundfile as sf
        audio_bytes = base64.b64decode(ref_audio_b64)
        audio_data, audio_sr = sf.read(io.BytesIO(audio_bytes))
        duration_s = round(len(audio_data) / audio_sr, 2)

        # Create clone prompt (CPU-heavy)
        func = functools.partial(
            self.engine.create_clone_prompt,
            ref_audio_b64=ref_audio_b64,
            ref_text=ref_text,
            x_vector_only_mode=not bool(ref_text),
        )
        prompt_item = await loop.run_in_executor(None, func)

        # Save to prompt store
        meta = self.prompt_store.save_prompt(
            name=name,
            prompt_item=prompt_item,
            tags=tags,
            ref_text=ref_text,
            ref_audio_duration_s=duration_s,
        )

        return TunnelMessage(
            type=MessageType.RESPONSE, request_id=request.request_id,
            body=json.dumps({"name": name, "status": "created", "metadata": meta.to_dict()}),
            headers={"Content-Type": "application/json"},
        )

    async def _handle_list_prompts(self, request: TunnelMessage) -> TunnelMessage:
        """GET /api/v1/voices/prompts — list saved clone prompts."""
        # Parse query params from path (e.g. /api/v1/voices/prompts?tags=maya,angry)
        tags = None
        path = request.path or ""
        if "?" in path:
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(path).query)
            if "tags" in qs:
                tags = qs["tags"][0].split(",")

        prompts = self.prompt_store.list_prompts(tags=tags)
        return TunnelMessage(
            type=MessageType.RESPONSE, request_id=request.request_id,
            body=json.dumps({"prompts": prompts, "count": len(prompts)}),
            headers={"Content-Type": "application/json"},
        )

    async def _handle_delete_prompt(self, request: TunnelMessage) -> TunnelMessage:
        """DELETE /api/v1/voices/prompts/{name} — delete a clone prompt."""
        path = request.path or ""
        name = path.rsplit("/", 1)[-1]

        deleted = self.prompt_store.delete_prompt(name)
        if not deleted:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=404, body=json.dumps({"error": f"Prompt '{name}' not found"}),
            )

        return TunnelMessage(
            type=MessageType.RESPONSE, request_id=request.request_id,
            body=json.dumps({"name": name, "status": "deleted"}),
            headers={"Content-Type": "application/json"},
        )

    async def _handle_synthesize_with_prompt(self, request: TunnelMessage) -> TunnelMessage:
        """POST /api/v1/tts/clone-prompt — synthesize with saved clone prompt."""
        err = self._require_base_model(request)
        if err:
            return err

        body = json.loads(request.body) if request.body else {}
        text = body.get("text")
        voice_prompt = body.get("voice_prompt")
        language = body.get("language", "Auto")
        fmt = body.get("format", "wav")

        if not text or not voice_prompt:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=400, body=json.dumps({"error": "Missing 'text' and 'voice_prompt'"}),
            )

        # Load cached prompt
        try:
            device = "cpu" if "cpu" in str(getattr(self.engine, '_device', 'cpu')) else "cuda"
            prompt_item = self.prompt_store.load_prompt(voice_prompt, device=device)
        except FileNotFoundError:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=404, body=json.dumps({"error": f"Clone prompt '{voice_prompt}' not found"}),
            )

        import functools
        from server.tts_engine import wav_to_format

        loop = asyncio.get_event_loop()
        func = functools.partial(self.engine.synthesize_with_clone_prompt, text=text, prompt_item=prompt_item, language=language)
        wav, sr = await loop.run_in_executor(None, func)

        audio_bytes = wav_to_format(wav, sr, fmt)
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

        return TunnelMessage(
            type=MessageType.RESPONSE, request_id=request.request_id,
            body=json.dumps({"audio": audio_b64, "format": fmt, "sample_rate": sr, "duration_s": round(len(wav) / sr, 2)}),
            headers={"Content-Type": "application/json"},
        )

    # ── Batch Endpoints ────────────────────────────────────────────

    async def _handle_batch_design(self, request: TunnelMessage) -> TunnelMessage:
        """POST /api/v1/voices/design/batch — generate multiple reference clips.

        Request body::

            {
                "items": [
                    {"name": "maya_neutral", "text": "...", "instruct": "...", "language": "English"},
                    {"name": "maya_happy", "text": "...", "instruct": "...", "language": "English"}
                ],
                "format": "wav",
                "create_prompts": true,   // also create clone prompts from each clip
                "prompt_tags_prefix": ["maya"]  // tags added to all prompts
            }
        """
        if not self.engine.is_loaded:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=503, body=json.dumps({"error": "TTS engine not loaded"}),
            )

        body = json.loads(request.body) if request.body else {}
        items = body.get("items", [])
        fmt = body.get("format", "wav")
        create_prompts = body.get("create_prompts", False)
        tags_prefix = body.get("prompt_tags_prefix", [])

        if not items:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=400, body=json.dumps({"error": "Missing 'items' array"}),
            )

        # Check if we need base model for prompt creation
        if create_prompts:
            err = self._require_base_model(request)
            if err:
                return err

        import functools
        from server.tts_engine import wav_to_format

        loop = asyncio.get_event_loop()
        results = []

        for i, item in enumerate(items):
            name = item.get("name", f"batch_{i}")
            text = item.get("text", "")
            instruct = item.get("instruct", "")
            language = item.get("language", "English")
            item_tags = item.get("tags", [])

            if not text or not instruct:
                results.append({"name": name, "status": "error", "error": "Missing text or instruct"})
                continue

            try:
                # Generate audio
                func = functools.partial(
                    self.engine.generate_voice_design,
                    text=text, description=instruct, language=language,
                )
                wav, sr = await loop.run_in_executor(None, func)
                audio_bytes = wav_to_format(wav, sr, fmt)
                audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
                duration_s = round(len(wav) / sr, 2)

                result = {
                    "name": name,
                    "status": "ok",
                    "audio": audio_b64,
                    "format": fmt,
                    "duration_s": duration_s,
                }

                # Optionally create clone prompt from this clip
                if create_prompts:
                    try:
                        prompt_func = functools.partial(
                            self.engine.create_clone_prompt,
                            ref_audio_b64=base64.b64encode(wav_to_format(wav, sr, "wav")).decode("ascii"),
                            ref_text=text,
                        )
                        prompt_item = await loop.run_in_executor(None, prompt_func)

                        all_tags = tags_prefix + item_tags
                        meta = self.prompt_store.save_prompt(
                            name=name,
                            prompt_item=prompt_item,
                            tags=all_tags,
                            ref_text=text,
                            ref_audio_duration_s=duration_s,
                        )
                        result["prompt_created"] = True
                        result["prompt_tags"] = all_tags
                    except Exception as e:
                        logger.exception("Failed to create prompt for %s", name)
                        result["prompt_created"] = False
                        result["prompt_error"] = str(e)

                results.append(result)
                logger.info("Batch design %d/%d: %s (%.1fs)", i + 1, len(items), name, duration_s)

            except Exception as e:
                logger.exception("Batch design failed for %s", name)
                results.append({"name": name, "status": "error", "error": str(e)})

        return TunnelMessage(
            type=MessageType.RESPONSE, request_id=request.request_id,
            body=json.dumps({
                "results": results,
                "total": len(items),
                "succeeded": sum(1 for r in results if r["status"] == "ok"),
            }),
            headers={"Content-Type": "application/json"},
        )

    async def _handle_batch_clone_prompt(self, request: TunnelMessage) -> TunnelMessage:
        """POST /api/v1/voices/clone-prompt/batch — create prompts from multiple ref files.

        Request body::

            {
                "items": [
                    {"name": "maya_neutral", "ref_audio_base64": "...", "ref_text": "...", "tags": [...]},
                    ...
                ]
            }
        """
        err = self._require_base_model(request)
        if err:
            return err

        body = json.loads(request.body) if request.body else {}
        items = body.get("items", [])

        if not items:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=400, body=json.dumps({"error": "Missing 'items' array"}),
            )

        import functools
        loop = asyncio.get_event_loop()
        results = []

        for i, item in enumerate(items):
            name = item.get("name", f"prompt_{i}")
            ref_audio_b64 = item.get("ref_audio_base64", "")
            ref_text = item.get("ref_text", "")
            tags = item.get("tags", [])

            if not ref_audio_b64:
                results.append({"name": name, "status": "error", "error": "Missing ref_audio_base64"})
                continue

            try:
                # Calculate duration
                import io, soundfile as sf
                audio_bytes = base64.b64decode(ref_audio_b64)
                audio_data, audio_sr = sf.read(io.BytesIO(audio_bytes))
                duration_s = round(len(audio_data) / audio_sr, 2)

                # Create prompt
                func = functools.partial(
                    self.engine.create_clone_prompt,
                    ref_audio_b64=ref_audio_b64,
                    ref_text=ref_text,
                    x_vector_only_mode=not bool(ref_text),
                )
                prompt_item = await loop.run_in_executor(None, func)

                meta = self.prompt_store.save_prompt(
                    name=name,
                    prompt_item=prompt_item,
                    tags=tags,
                    ref_text=ref_text,
                    ref_audio_duration_s=duration_s,
                )
                results.append({"name": name, "status": "created", "duration_s": duration_s, "tags": tags})
                logger.info("Batch prompt %d/%d: %s", i + 1, len(items), name)

            except Exception as e:
                logger.exception("Batch prompt failed for %s", name)
                results.append({"name": name, "status": "error", "error": str(e)})

        return TunnelMessage(
            type=MessageType.RESPONSE, request_id=request.request_id,
            body=json.dumps({
                "results": results,
                "total": len(items),
                "succeeded": sum(1 for r in results if r["status"] in ("created", "ok")),
            }),
            headers={"Content-Type": "application/json"},
        )

    # ── Voice Casting ─────────────────────────────────────────────

    async def _handle_list_emotions(self, request: TunnelMessage) -> TunnelMessage:
        """GET /api/v1/voices/emotions — list available emotion presets."""
        from server.emotion_presets import EMOTION_PRESETS, EMOTION_ORDER
        
        emotions = []
        for name in EMOTION_ORDER:
            preset = EMOTION_PRESETS[name]
            emotions.append({
                "name": preset.name,
                "instruct": preset.instruct,
                "ref_text": preset.ref_text,
                "tags": preset.tags,
            })
        
        return TunnelMessage(
            type=MessageType.RESPONSE, request_id=request.request_id,
            body=json.dumps({"emotions": emotions, "count": len(emotions)}),
            headers={"Content-Type": "application/json"},
        )

    async def _handle_cast_voice(self, request: TunnelMessage) -> TunnelMessage:
        """POST /api/v1/voices/cast — run full emotion casting for a character.

        Generates all emotion variants via VoiceDesign and creates clone prompts.

        Request body::

            {
                "character": "maya",
                "description": "Young woman, warm alto voice, slight vulnerability",
                "emotions": ["neutral", "happy", "angry"],  // optional, defaults to all
                "text_overrides": {"happy": "Custom happy text..."},  // optional
                "language": "English",
                "format": "wav"
            }

        Returns results for each emotion with audio + prompt status.
        """
        if not self.engine.is_loaded:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=503, body=json.dumps({"error": "TTS engine not loaded"}),
            )

        # Check base model for prompt creation
        err = self._require_base_model(request)
        if err:
            return err

        body = json.loads(request.body) if request.body else {}
        character = body.get("character")
        description = body.get("description")
        emotions = body.get("emotions")  # None = all
        text_overrides = body.get("text_overrides", {})
        language = body.get("language", "English")
        fmt = body.get("format", "wav")

        if not character or not description:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=400, body=json.dumps({"error": "Missing 'character' and 'description'"}),
            )

        from server.emotion_presets import build_casting_batch

        items = build_casting_batch(
            character_name=character,
            base_description=description,
            emotions=emotions,
            text_overrides=text_overrides,
        )

        # Build a batch design request with prompt creation
        batch_body = json.dumps({
            "items": items,
            "format": fmt,
            "create_prompts": True,
            "prompt_tags_prefix": [character],
        })

        # Reuse batch handler
        batch_request = TunnelMessage(
            type=MessageType.REQUEST,
            request_id=request.request_id,
            path="/api/v1/voices/design/batch",
            method="POST",
            body=batch_body,
        )
        return await self._handle_batch_design(batch_request)

    # ── Audio Processing ────────────────────────────────────────────

    async def _handle_normalize(self, request: TunnelMessage) -> TunnelMessage:
        """POST /api/v1/audio/normalize — formant-normalize audio.

        Request body::

            {
                "target_audio_base64": "...",
                "reference_audio_base64": "...",
                "strength": 0.7,  // 0.0-1.0, default 0.7
                "format": "wav"
            }
        """
        body = json.loads(request.body) if request.body else {}
        target_b64 = body.get("target_audio_base64")
        ref_b64 = body.get("reference_audio_base64")
        strength = body.get("strength", 0.7)
        fmt = body.get("format", "wav")

        if not target_b64 or not ref_b64:
            return TunnelMessage(
                type=MessageType.RESPONSE, request_id=request.request_id,
                status_code=400,
                body=json.dumps({"error": "Missing 'target_audio_base64' and 'reference_audio_base64'"}),
            )

        import functools
        from server.audio_normalize import normalize_audio_bytes
        from server.tts_engine import wav_to_format

        loop = asyncio.get_event_loop()
        target_bytes = base64.b64decode(target_b64)
        ref_bytes = base64.b64decode(ref_b64)

        func = functools.partial(normalize_audio_bytes, target_bytes, ref_bytes, strength=strength)
        wav_bytes, sr = await loop.run_in_executor(None, func)

        # Convert to requested format
        if fmt != "wav":
            import io, numpy as np, soundfile as sf
            audio_data, audio_sr = sf.read(io.BytesIO(wav_bytes))
            audio_bytes = wav_to_format(audio_data.astype(np.float32), audio_sr, fmt)
        else:
            audio_bytes = wav_bytes

        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

        return TunnelMessage(
            type=MessageType.RESPONSE, request_id=request.request_id,
            body=json.dumps({"audio": audio_b64, "format": fmt, "sample_rate": sr}),
            headers={"Content-Type": "application/json"},
        )

    async def _auto_sync_voice(self, voice_id: str) -> None:
        """Auto-sync a single voice package to the relay."""
        try:
            logger.info(f"Auto-syncing voice package: {voice_id}")
            
            # Export the voice package
            package_path = self.voice_packager.export_package(voice_id)
            with open(package_path, "rb") as f:
                package_data = f.read()
            
            # Clean up temp file
            package_path.unlink()
            
            # Send sync notification to relay (this would be implementation-specific)
            # For now, we just log it - the relay would need to implement this endpoint
            logger.info(f"Voice package {voice_id} ready for sync ({len(package_data)} bytes)")
            
        except Exception as e:
            logger.error(f"Failed to auto-sync voice {voice_id}: {e}")


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
