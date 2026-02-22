"""Remote relay server — runs on the OpenClaw droplet (no GPU).

Accepts WebSocket tunnel connections from local GPU machines and exposes
a REST API that forwards requests through the tunnel.
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
from aiohttp import web

from server.auth import AuthManager, extract_api_key
from server.tunnel import TunnelServer

logger = logging.getLogger(__name__)


class RemoteRelay:
    """REST API relay that forwards requests to the local GPU via WebSocket tunnel."""

    def __init__(self, config: dict) -> None:
        """Initialize the relay.

        Args:
            config: Parsed configuration dict.
        """
        self.config = config
        self.api_key = config["api_key"]
        self.auth_manager = AuthManager(self.api_key)
        self.tunnel_server = TunnelServer()
        self.start_time = time.time()

        remote = config.get("remote", {})
        self.host = remote.get("bind", "0.0.0.0")
        self.port = remote.get("port", 9800)

    def _check_auth(self, request: web.Request) -> bool:
        """Validate API key from request headers.

        Args:
            request: The aiohttp request.

        Returns:
            True if authenticated.
        """
        token = self.auth_manager.authenticate(dict(request.headers))
        return token is not None

    async def _require_auth(self, request: web.Request) -> Optional[web.Response]:
        """Check auth and return error response if invalid.

        Args:
            request: The aiohttp request.

        Returns:
            Error response if auth fails, None if OK.
        """
        if not self._check_auth(request):
            return web.json_response(
                {"error": "Unauthorized — provide API key via Authorization: Bearer <key>"},
                status=401,
            )
        return None

    async def _require_tunnel(self) -> Optional[web.Response]:
        """Check if tunnel client is connected.

        Returns:
            Error response if no client, None if OK.
        """
        if not self.tunnel_server.has_client:
            return web.json_response(
                {"error": "No GPU server connected. Start the local server first."},
                status=503,
            )
        return None

    async def _forward_to_local(
        self,
        method: str,
        path: str,
        body: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 300,
    ) -> web.Response:
        """Forward a request through the tunnel and return the response.

        Args:
            method: HTTP method.
            path: API path.
            body: Request body as JSON string.
            headers: Additional headers.
            timeout: Timeout in seconds.

        Returns:
            aiohttp Response.
        """
        try:
            response = await self.tunnel_server.send_request(
                method=method,
                path=path,
                body=body,
                headers=headers,
                timeout=timeout,
            )

            status = response.status_code
            resp_body = response.body or "{}"
            content_type = (response.headers or {}).get("Content-Type", "application/json")

            # If response contains base64 audio, decode and return as binary
            if response.body_binary:
                try:
                    data = json.loads(resp_body)
                    if "audio" in data:
                        audio_bytes = base64.b64decode(data["audio"])
                        fmt = data.get("format", "wav")
                        content_type = f"audio/{fmt}"
                        return web.Response(
                            body=audio_bytes,
                            status=status,
                            content_type=content_type,
                            headers={
                                "X-Duration-Seconds": str(data.get("duration_seconds", 0)),
                                "X-Sample-Rate": str(data.get("sample_rate", 24000)),
                                "X-Voice-ID": data.get("voice_id", ""),
                            },
                        )
                except (json.JSONDecodeError, KeyError):
                    pass

            return web.Response(
                text=resp_body,
                status=status,
                content_type=content_type,
            )

        except ConnectionError as e:
            return web.json_response({"error": str(e)}, status=503)
        except TimeoutError as e:
            return web.json_response({"error": str(e)}, status=504)
        except Exception as e:
            logger.exception("Error forwarding request")
            return web.json_response({"error": str(e)}, status=500)

    # --- Route handlers ---

    async def handle_status(self, request: web.Request) -> web.Response:
        """GET /api/v1/status — relay status + forward to local if connected."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error

        relay_status = {
            "relay": "ok",
            "tunnel_connected": self.tunnel_server.has_client,
            "connected_clients": self.tunnel_server.connected_clients,
            "uptime_seconds": round(time.time() - self.start_time, 1),
        }

        if self.tunnel_server.has_client:
            try:
                local_response = await self.tunnel_server.send_request("GET", "/api/v1/status")
                local_status = json.loads(local_response.body or "{}")
                relay_status["local"] = local_status
            except Exception as e:
                relay_status["local"] = {"error": str(e)}

        return web.json_response(relay_status)

    async def handle_voices(self, request: web.Request) -> web.Response:
        """GET /api/v1/tts/voices."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error

        return await self._forward_to_local("GET", "/api/v1/tts/voices")

    async def handle_synthesize(self, request: web.Request) -> web.Response:
        """POST /api/v1/tts/synthesize."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error

        body = await request.text()
        return await self._forward_to_local("POST", "/api/v1/tts/synthesize", body=body)

    async def handle_clone(self, request: web.Request) -> web.Response:
        """POST /api/v1/tts/clone."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error

        # Allowed audio MIME types for clone uploads
        ALLOWED_AUDIO_TYPES = {
            "audio/wav", "audio/x-wav", "audio/wave",
            "audio/mpeg", "audio/mp3",
            "audio/ogg", "audio/flac",
            "audio/webm", "audio/mp4",
            "application/octet-stream",
        }

        # Handle multipart upload
        if request.content_type == "multipart/form-data":
            reader = await request.multipart()
            voice_name = None
            audio_b64 = None

            async for part in reader:
                if part.name == "voice_name":
                    voice_name = (await part.read()).decode("utf-8")
                elif part.name == "reference_audio":
                    ct = part.headers.get("Content-Type", "application/octet-stream")
                    if ct not in ALLOWED_AUDIO_TYPES:
                        return web.json_response(
                            {"error": f"Invalid audio type: {ct}. Allowed: wav, mp3, ogg, flac"},
                            status=400,
                        )
                    audio_data = await part.read()
                    audio_b64 = base64.b64encode(audio_data).decode("ascii")

            body = json.dumps({"voice_name": voice_name, "reference_audio": audio_b64})
        else:
            body = await request.text()

        return await self._forward_to_local("POST", "/api/v1/tts/clone", body=body)

    async def handle_delete_voice(self, request: web.Request) -> web.Response:
        """DELETE /api/v1/tts/voices/{voice_id}."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error

        voice_id = request.match_info["voice_id"]
        return await self._forward_to_local("DELETE", f"/api/v1/tts/voices/{voice_id}")

    async def handle_design(self, request: web.Request) -> web.Response:
        """POST /api/v1/tts/design."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error

        body = await request.text()
        return await self._forward_to_local("POST", "/api/v1/tts/design", body=body)

    async def handle_websocket_tunnel(self, request: web.Request) -> web.WebSocketResponse:
        """WebSocket endpoint for tunnel connections from local GPU machines."""
        ws = web.WebSocketResponse(max_msg_size=50 * 1024 * 1024)
        await ws.prepare(request)

        logger.info("New WebSocket tunnel connection from %s", request.remote)

        # Wrap aiohttp WebSocket to match websockets interface
        adapter = AioHTTPWebSocketAdapter(ws)
        await self.tunnel_server.handle_connection(adapter)

        return ws

    def create_app(self) -> web.Application:
        """Create the aiohttp application with all routes.

        Returns:
            Configured aiohttp Application.
        """
        app = web.Application()

        # API routes
        app.router.add_get("/api/v1/status", self.handle_status)
        app.router.add_get("/api/v1/tts/voices", self.handle_voices)
        app.router.add_post("/api/v1/tts/synthesize", self.handle_synthesize)
        app.router.add_post("/api/v1/tts/clone", self.handle_clone)
        app.router.add_post("/api/v1/tts/design", self.handle_design)
        app.router.add_delete("/api/v1/tts/voices/{voice_id}", self.handle_delete_voice)

        # WebSocket tunnel endpoint
        app.router.add_get("/ws/tunnel", self.handle_websocket_tunnel)

        return app

    def run(self) -> None:
        """Start the relay server."""
        app = self.create_app()
        logger.info("Starting remote relay on %s:%d", self.host, self.port)
        logger.info("Tunnel endpoint: ws://%s:%d/ws/tunnel", self.host, self.port)
        logger.info("API base: http://%s:%d/api/v1/", self.host, self.port)
        web.run_app(app, host=self.host, port=self.port, print=None)


class AioHTTPWebSocketAdapter:
    """Adapter to make aiohttp WebSocket look like a websockets WebSocket.

    The TunnelServer expects a websockets-style interface, so we wrap
    the aiohttp WebSocket to match.
    """

    def __init__(self, ws: web.WebSocketResponse) -> None:
        self._ws = ws
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._closed = False
        self._receive_task: Optional[asyncio.Task] = None
        self.remote_address = ("aiohttp-client",)

    async def _start_receiving(self) -> None:
        """Start receiving messages into the queue."""
        import aiohttp

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._queue.put(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    break
        finally:
            self._closed = True

    async def recv(self) -> str:
        """Receive a message."""
        if self._receive_task is None:
            self._receive_task = asyncio.create_task(self._start_receiving())
            # Give the receiving task a moment to start
            await asyncio.sleep(0.001)

        if self._closed and self._queue.empty():
            raise ConnectionError("WebSocket closed")

        return await self._queue.get()

    async def send(self, data: str) -> None:
        """Send a message."""
        if self._closed or self._ws.closed:
            raise ConnectionError("WebSocket closed")
        try:
            await self._ws.send_str(data)
        except Exception as e:
            self._closed = True
            raise ConnectionError(f"Failed to send: {e}")

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Close the connection."""
        await self._ws.close(code=code, message=reason.encode())
        self._closed = True

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        try:
            return await self.recv()
        except (ConnectionError, asyncio.CancelledError):
            raise StopAsyncIteration


def load_config(config_path: str = "config.yaml") -> dict:
    """Load relay configuration."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file '{config_path}' not found.")

    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config.get("api_key") or config["api_key"] == "CHANGE_ME":
        raise ValueError("api_key must be set in config.yaml")

    return config


def setup_logging(config: dict) -> None:
    """Configure logging."""
    log_config = config.get("logging", {})
    level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main() -> None:
    """Entry point for the remote relay server."""
    config_path = os.environ.get("QWEN3_TTS_CONFIG", "config.yaml")

    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    setup_logging(config)
    relay = RemoteRelay(config)
    relay.run()


if __name__ == "__main__":
    main()
