#!/usr/bin/env python3
"""Bridge server — runs on OpenClaw side.

Accepts WebSocket tunnel from the GPU machine and exposes an HTTP API
for OpenClaw to send TTS requests.
"""

import asyncio
import base64
import json
import logging
import os
import ssl
import time
import uuid
from collections import defaultdict
from pathlib import Path

import websockets
from aiohttp import web

# Inline config for bridge (doesn't need full server config)
from dotenv import load_dotenv
load_dotenv()

AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
BRIDGE_WS_PORT = int(os.getenv("BRIDGE_WS_PORT", "8765"))
BRIDGE_HTTP_PORT = int(os.getenv("BRIDGE_HTTP_PORT", "8766"))
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "30"))
SSL_CERT = os.getenv("SSL_CERT", "")
SSL_KEY = os.getenv("SSL_KEY", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("tts-bridge")


import hashlib
import hmac

def sign_message(payload: dict) -> dict:
    payload["_ts"] = int(time.time())
    msg = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    sig = hmac.new(AUTH_TOKEN.encode(), msg.encode(), hashlib.sha256).hexdigest()
    payload["_sig"] = sig
    return payload

def verify_message(payload: dict) -> bool:
    sig = payload.pop("_sig", None)
    ts = payload.get("_ts", 0)
    if not sig or abs(time.time() - ts) > 300:
        return False
    msg = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    expected = hmac.new(AUTH_TOKEN.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


class BridgeServer:
    """Manages the tunnel connection and HTTP API."""

    def __init__(self):
        self._tunnel_ws = None
        self._pending: dict[str, asyncio.Future] = {}
        self._request_times: list[float] = []
        self._gpu_health: dict = {}

    @property
    def is_connected(self) -> bool:
        return self._tunnel_ws is not None and not self._tunnel_ws.closed

    def _check_rate_limit(self) -> bool:
        now = time.time()
        self._request_times = [t for t in self._request_times if now - t < 60]
        if len(self._request_times) >= RATE_LIMIT:
            return False
        self._request_times.append(now)
        return True

    # ── WebSocket tunnel handler ─────────────────────────────────────
    async def handle_tunnel(self, ws):
        """Handle incoming tunnel connection from GPU machine."""
        # Verify auth
        auth = ws.request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], AUTH_TOKEN):
            logger.warning("Tunnel auth failed from %s", ws.remote_address)
            await ws.close(4001, "Unauthorized")
            return

        if self._tunnel_ws and not self._tunnel_ws.closed:
            logger.warning("Replacing existing tunnel connection")
            await self._tunnel_ws.close(4002, "Replaced by new connection")

        self._tunnel_ws = ws
        logger.info("GPU tunnel connected from %s", ws.remote_address)

        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    if not verify_message(msg):
                        logger.warning("Invalid signature on tunnel message")
                        continue

                    msg_type = msg.get("type", "")

                    if msg_type == "hello":
                        self._gpu_health = msg.get("health", {})
                        logger.info("GPU hello: models=%s", msg.get("models"))
                        continue

                    # Route response to pending request
                    req_id = msg.get("request_id", "")
                    if req_id in self._pending:
                        self._pending[req_id].set_result(msg)
                    else:
                        logger.warning("No pending request for id: %s", req_id)

                except json.JSONDecodeError:
                    logger.error("Invalid JSON from tunnel")
        except websockets.ConnectionClosed:
            logger.warning("GPU tunnel disconnected")
        finally:
            if self._tunnel_ws is ws:
                self._tunnel_ws = None

    async def _send_to_gpu(self, request: dict, timeout: float = 120) -> dict:
        """Send request through tunnel and wait for response."""
        if not self.is_connected:
            raise web.HTTPServiceUnavailable(text="GPU not connected")

        request_id = str(uuid.uuid4())
        request["request_id"] = request_id

        future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        try:
            signed = sign_message(request)
            await self._tunnel_ws.send(json.dumps(signed))
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise web.HTTPGatewayTimeout(text="GPU render timeout")
        finally:
            self._pending.pop(request_id, None)

    # ── HTTP API handlers ────────────────────────────────────────────
    async def handle_generate(self, request: web.Request) -> web.Response:
        """POST /api/tts/generate"""
        if not self._check_rate_limit():
            return web.json_response({"error": "Rate limit exceeded"}, status=429)

        body = await request.json()
        text = body.get("text", "")
        if not text:
            return web.json_response({"error": "text is required"}, status=400)

        msg = {
            "type": "generate",
            "text": text,
            "voice": body.get("voice", ""),
            "voice_config": body.get("voice_config", {}),
            "output_format": body.get("output_format", "mp3"),
        }

        resp = await self._send_to_gpu(msg)

        if resp.get("type") == "error":
            return web.json_response({"error": resp.get("error")}, status=500)

        audio_bytes = base64.b64decode(resp.get("audio", ""))
        fmt = resp.get("format", "mp3")
        content_type = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "ogg": "audio/ogg",
        }.get(fmt, "application/octet-stream")

        return web.Response(
            body=audio_bytes,
            content_type=content_type,
            headers={
                "X-Duration": str(resp.get("duration_s", 0)),
                "X-Render-Time": str(resp.get("render_time_s", 0)),
            },
        )

    async def handle_voices(self, request: web.Request) -> web.Response:
        """GET /api/tts/voices"""
        resp = await self._send_to_gpu({"type": "voices"})
        return web.json_response(resp.get("data", []))

    async def handle_health(self, request: web.Request) -> web.Response:
        """GET /api/tts/health"""
        if not self.is_connected:
            return web.json_response(
                {"status": "disconnected", "gpu_connected": False}, status=503
            )
        resp = await self._send_to_gpu({"type": "health"}, timeout=10)
        data = resp.get("data", {})
        data["gpu_connected"] = True
        return web.json_response(data)

    async def handle_clone(self, request: web.Request) -> web.Response:
        """POST /api/tts/clone"""
        if not self._check_rate_limit():
            return web.json_response({"error": "Rate limit exceeded"}, status=429)

        body = await request.json()
        msg = {
            "type": "clone",
            "name": body.get("name", ""),
            "reference_audio": body.get("reference_audio", ""),
            "ref_text": body.get("ref_text", ""),
            "description": body.get("description", ""),
        }
        resp = await self._send_to_gpu(msg)

        if resp.get("type") == "error":
            return web.json_response({"error": resp.get("error")}, status=500)
        return web.json_response(resp.get("data", {}))


async def start_bridge():
    bridge = BridgeServer()

    # Auth middleware
    @web.middleware
    async def auth_middleware(request, handler):
        # Health endpoint is public
        if request.path == "/api/tts/health":
            return await handler(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], AUTH_TOKEN):
            return web.json_response({"error": "Unauthorized"}, status=401)
        return await handler(request)

    # HTTP API
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_post("/api/tts/generate", bridge.handle_generate)
    app.router.add_get("/api/tts/voices", bridge.handle_voices)
    app.router.add_get("/api/tts/health", bridge.handle_health)
    app.router.add_post("/api/tts/clone", bridge.handle_clone)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", BRIDGE_HTTP_PORT)
    await site.start()
    logger.info("HTTP API listening on port %d", BRIDGE_HTTP_PORT)

    # WebSocket tunnel server
    ssl_ctx = None
    if SSL_CERT and SSL_KEY:
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(SSL_CERT, SSL_KEY)

    ws_server = await websockets.serve(
        bridge.handle_tunnel,
        "0.0.0.0",
        BRIDGE_WS_PORT,
        ssl=ssl_ctx,
        max_size=50 * 1024 * 1024,
        ping_interval=30,
        ping_timeout=10,
    )
    logger.info("WebSocket tunnel listening on port %d%s", BRIDGE_WS_PORT, " (TLS)" if ssl_ctx else "")

    # Run forever
    stop = asyncio.Event()
    await stop.wait()


def run():
    asyncio.run(start_bridge())


if __name__ == "__main__":
    run()
