#!/usr/bin/env python3
"""Bridge server — runs on OpenClaw side.

Accepts WebSocket tunnel from the GPU machine and exposes an HTTP API
for OpenClaw to send TTS requests. Uses the TunnelMessage protocol
from server.tunnel for consistency.
"""

import asyncio
import base64
import json
import logging
import os
import ssl
import time
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
BRIDGE_HTTP_HOST = os.getenv("BRIDGE_HTTP_HOST", "127.0.0.1")
BRIDGE_HTTP_PORT = int(os.getenv("BRIDGE_HTTP_PORT", "8766"))
BRIDGE_WS_HOST = os.getenv("BRIDGE_WS_HOST", "127.0.0.1")
BRIDGE_WS_PORT = int(os.getenv("BRIDGE_WS_PORT", "8765"))
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "30"))
SSL_CERT = os.getenv("SSL_CERT", "")
SSL_KEY = os.getenv("SSL_KEY", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Allowed audio MIME types for clone uploads
ALLOWED_AUDIO_TYPES = {
    "audio/wav", "audio/x-wav", "audio/wave",
    "audio/mpeg", "audio/mp3",
    "audio/ogg", "audio/flac",
    "audio/webm", "audio/mp4",
    "application/octet-stream",  # fallback for unknown
}

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("tts-bridge")

# Import tunnel protocol types
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from server.tunnel import MessageType, TunnelMessage, TunnelServer


class BridgeServer:
    """Manages the tunnel connection and HTTP API using TunnelMessage protocol."""

    def __init__(self):
        self.tunnel_server = TunnelServer()
        self._request_times: list[float] = []

    @property
    def is_connected(self) -> bool:
        return self.tunnel_server.has_client

    def _check_rate_limit(self) -> bool:
        now = time.time()
        self._request_times = [t for t in self._request_times if now - t < 60]
        if len(self._request_times) >= RATE_LIMIT:
            return False
        self._request_times.append(now)
        return True

    async def _forward_to_gpu(
        self,
        method: str,
        path: str,
        body: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 600,
    ) -> web.Response:
        """Forward a request through the tunnel."""
        if not self.is_connected:
            return web.json_response(
                {"error": "GPU not connected"}, status=503
            )

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
            content_type = (response.headers or {}).get(
                "Content-Type", "application/json"
            )

            # If response contains base64 audio, decode it
            if response.body_binary:
                try:
                    data = json.loads(resp_body)
                    if "audio" in data:
                        audio_bytes = base64.b64decode(data["audio"])
                        fmt = data.get("format", "wav")
                        return web.Response(
                            body=audio_bytes,
                            status=status,
                            content_type=f"audio/{fmt}",
                            headers={
                                "X-Duration-Seconds": str(
                                    data.get("duration_seconds", 0)
                                ),
                                "X-Sample-Rate": str(data.get("sample_rate", 24000)),
                                "X-Voice-ID": data.get("voice_id", ""),
                            },
                        )
                except (json.JSONDecodeError, KeyError):
                    pass

            return web.Response(text=resp_body, status=status, content_type=content_type)

        except ConnectionError as e:
            return web.json_response({"error": str(e)}, status=503)
        except TimeoutError as e:
            return web.json_response({"error": str(e)}, status=504)
        except Exception as e:
            logger.exception("Error forwarding request")
            return web.json_response({"error": str(e)}, status=500)

    # ── HTTP API handlers ────────────────────────────────────────────

    async def handle_health(self, request: web.Request) -> web.Response:
        """GET /api/v1/status"""
        status = {
            "relay": "ok",
            "tunnel_connected": self.is_connected,
            "connected_clients": self.tunnel_server.connected_clients,
        }
        if self.is_connected:
            try:
                resp = await self.tunnel_server.send_request("GET", "/api/v1/status")
                local_status = json.loads(resp.body or "{}")
                status["local"] = local_status
            except Exception as e:
                status["local"] = {"error": str(e)}
        return web.json_response(status)

    async def handle_synthesize(self, request: web.Request) -> web.Response:
        """POST /api/v1/tts/synthesize"""
        if not self._check_rate_limit():
            return web.json_response({"error": "Rate limit exceeded"}, status=429)
        body = await request.text()
        return await self._forward_to_gpu("POST", "/api/v1/tts/synthesize", body=body)

    async def handle_voices(self, request: web.Request) -> web.Response:
        """GET /api/v1/tts/voices"""
        return await self._forward_to_gpu("GET", "/api/v1/tts/voices")

    async def handle_clone(self, request: web.Request) -> web.Response:
        """POST /api/v1/tts/clone"""
        if not self._check_rate_limit():
            return web.json_response({"error": "Rate limit exceeded"}, status=429)

        if request.content_type == "multipart/form-data":
            reader = await request.multipart()
            voice_name = None
            audio_b64 = None

            async for part in reader:
                if part.name == "voice_name":
                    voice_name = (await part.read()).decode("utf-8")
                elif part.name == "reference_audio":
                    # Validate file type
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

        return await self._forward_to_gpu("POST", "/api/v1/tts/clone", body=body)

    async def handle_design(self, request: web.Request) -> web.Response:
        """POST /api/v1/tts/design"""
        body = await request.text()
        return await self._forward_to_gpu("POST", "/api/v1/tts/design", body=body)

    async def handle_websocket_tunnel(self, request: web.Request) -> web.WebSocketResponse:
        """WebSocket endpoint for tunnel connections from local GPU machines."""
        ws = web.WebSocketResponse(max_msg_size=50 * 1024 * 1024)
        await ws.prepare(request)
        logger.info("New WebSocket tunnel connection from %s", request.remote)

        from server.remote_relay import AioHTTPWebSocketAdapter
        adapter = AioHTTPWebSocketAdapter(ws)
        await self.tunnel_server.handle_connection(adapter)
        return ws


import hmac


async def start_bridge():
    bridge = BridgeServer()

    # Auth middleware
    @web.middleware
    async def auth_middleware(request, handler):
        # Health endpoint is public
        if request.path == "/api/v1/status" and request.method == "GET":
            return await handler(request)
        # Tunnel WebSocket uses its own auth handshake
        if request.path == "/ws/tunnel":
            return await handler(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or not hmac.compare_digest(
            auth[7:], AUTH_TOKEN
        ):
            return web.json_response({"error": "Unauthorized"}, status=401)
        return await handler(request)

    # HTTP API
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/api/v1/status", bridge.handle_health)
    app.router.add_get("/api/v1/tts/voices", bridge.handle_voices)
    app.router.add_post("/api/v1/tts/synthesize", bridge.handle_synthesize)
    app.router.add_post("/api/v1/tts/clone", bridge.handle_clone)
    app.router.add_post("/api/v1/tts/design", bridge.handle_design)
    app.router.add_get("/ws/tunnel", bridge.handle_websocket_tunnel)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, BRIDGE_HTTP_HOST, BRIDGE_HTTP_PORT)
    await site.start()
    logger.info("HTTP API listening on %s:%d", BRIDGE_HTTP_HOST, BRIDGE_HTTP_PORT)

    # Run forever
    stop = asyncio.Event()
    await stop.wait()


def run():
    asyncio.run(start_bridge())


if __name__ == "__main__":
    run()
