"""Remote relay server — runs on the OpenClaw droplet (no GPU).

Accepts WebSocket tunnel connections from local GPU machines and exposes
a REST API that forwards requests through the tunnel.
"""

from __future__ import annotations

import asyncio
import base64
import gc
import json
import logging
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Optional

import yaml
from aiohttp import web

from server.auth import AuthManager, extract_api_key
from server.runpod_client import RunPodClient
from server.tunnel import TunnelServer

logger = logging.getLogger(__name__)

# Debug log ring buffer
_debug_log: deque[dict] = deque(maxlen=500)
_debug_subscribers: set[web.WebSocketResponse] = set()


def debug_event(event_type: str, **kwargs) -> None:
    """Record a debug event and broadcast to subscribers."""
    entry = {"t": time.time(), "type": event_type, **kwargs}
    _debug_log.append(entry)
    # Fire-and-forget broadcast to debug subscribers
    dead = []
    for ws in _debug_subscribers:
        if ws.closed:
            dead.append(ws)
            continue
        try:
            asyncio.ensure_future(ws.send_json(entry))
        except Exception:
            dead.append(ws)
    for ws in dead:
        _debug_subscribers.discard(ws)


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

        # RunPod fallback
        runpod_cfg = config.get("runpod", {})
        runpod_endpoint = runpod_cfg.get("endpoint_id") or os.environ.get("RUNPOD_ENDPOINT_ID", "")
        runpod_key = runpod_cfg.get("api_key") or os.environ.get("RUNPOD_API_KEY", "")
        if runpod_endpoint and runpod_key:
            self.runpod = RunPodClient(runpod_endpoint, runpod_key, self.api_key)
            logger.info("RunPod fallback configured: endpoint=%s", runpod_endpoint)
        else:
            self.runpod = None
            logger.info("RunPod fallback not configured")

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

    @property
    def has_gpu_backend(self) -> bool:
        """Check if any GPU backend is available (tunnel or RunPod)."""
        return self.tunnel_server.has_client or self.runpod is not None

    async def _require_tunnel(self) -> Optional[web.Response]:
        """Check if tunnel client is connected.

        Returns:
            Error response if no client AND no RunPod fallback, None if OK.
        """
        if not self.tunnel_server.has_client and not self.runpod:
            return web.json_response(
                {"error": "No GPU server connected and no RunPod fallback configured."},
                status=503,
            )
        return None

    async def _forward_to_runpod(
        self, endpoint: str, body: dict | None = None, timeout: float = 90
    ) -> web.Response:
        """Forward a request to RunPod serverless.

        Returns an aiohttp web.Response with the audio or JSON result.
        """
        try:
            debug_event("runpod_forward_start", endpoint=endpoint)
            result = await self.runpod.runsync(endpoint, body, timeout=timeout)
            debug_event("runpod_forward_done", endpoint=endpoint, status=result.get("status"))

            if result.get("status") == "COMPLETED":
                output = result.get("output", {})
                # If output has audio, decode and return as binary
                if "audio" in output:
                    audio_bytes = base64.b64decode(output["audio"])
                    fmt = output.get("format", "wav")
                    return web.Response(
                        body=audio_bytes,
                        status=200,
                        content_type=f"audio/{fmt}",
                        headers={
                            "X-Duration-Seconds": str(output.get("duration_s", 0)),
                            "X-Backend": "runpod",
                            "X-Execution-Ms": str(result.get("executionTime", 0)),
                        },
                    )
                # Otherwise return JSON
                return web.json_response(output)
            else:
                error = result.get("error", "Unknown RunPod error")
                return web.json_response({"error": error, "backend": "runpod"}, status=502)

        except asyncio.TimeoutError:
            return web.json_response({"error": "RunPod request timed out"}, status=504)
        except Exception as e:
            logger.exception("RunPod forward error")
            return web.json_response({"error": f"RunPod error: {e}"}, status=502)

    async def _forward_with_fallback(
        self,
        method: str,
        path: str,
        body: str | None = None,
        runpod_endpoint: str | None = None,
        runpod_body: dict | None = None,
        timeout: float = 300,
    ) -> web.Response:
        """Forward to tunnel if connected, otherwise fall back to RunPod.

        Args:
            method: HTTP method for tunnel forwarding.
            path: API path for tunnel forwarding.
            body: Request body as JSON string (for tunnel).
            runpod_endpoint: RunPod endpoint path (defaults to path).
            runpod_body: RunPod body dict (defaults to parsed body).
            timeout: Timeout in seconds.
        """
        if self.tunnel_server.has_client:
            return await self._forward_to_local(method, path, body=body, timeout=timeout)
        elif self.runpod:
            rp_endpoint = runpod_endpoint or path
            rp_body = runpod_body if runpod_body is not None else (json.loads(body) if body else {})
            return await self._forward_to_runpod(rp_endpoint, rp_body, timeout=timeout)
        else:
            return web.json_response(
                {"error": "No GPU backend available (tunnel disconnected, no RunPod configured)"},
                status=503,
            )

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
            debug_event("forward_start", method=method, path=path)
            response = await self.tunnel_server.send_request(
                method=method,
                path=path,
                body=body,
                headers=headers,
                timeout=timeout,
            )
            debug_event("forward_done", method=method, path=path, status=response.status_code)

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
        debug_event("synth_start", body_len=len(body))
        try:
            resp = await self._forward_to_local("POST", "/api/v1/tts/synthesize", body=body)
            debug_event("synth_done", status=resp.status, body_len=resp.body_length if hasattr(resp, 'body_length') else 0)
            return resp
        finally:
            # Force GC to reclaim large audio buffers
            gc.collect()

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

    async def handle_export_package(self, request: web.Request) -> web.Response:
        """GET /api/v1/tts/voices/{voice_id}/package — download voice package."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error

        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error

        voice_id = request.match_info["voice_id"]
        path = f"/api/v1/tts/voices/{voice_id}/package"
        
        try:
            # Forward to local server
            response = await self.tunnel_server.send_request("GET", path, timeout=60)
            
            if response.status_code != 200:
                return web.Response(
                    text=response.body or "{}",
                    status=response.status_code,
                    content_type="application/json"
                )
            
            # Parse response and extract package data
            data = json.loads(response.body or "{}")
            package_b64 = data.get("package")
            filename = data.get("filename", f"{voice_id}.voicepkg.zip")
            
            if not package_b64:
                return web.json_response({"error": "Invalid package response"}, status=500)
            
            # Decode and return as file download
            package_bytes = base64.b64decode(package_b64)
            
            return web.Response(
                body=package_bytes,
                content_type="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Content-Length": str(len(package_bytes)),
                }
            )
            
        except Exception as e:
            logger.exception("Error exporting voice package")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_import_package(self, request: web.Request) -> web.Response:
        """POST /api/v1/tts/voices/import — upload voice package."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error

        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error

        try:
            # Handle multipart file upload or raw binary body
            if request.content_type and request.content_type.startswith("multipart/"):
                reader = await request.multipart()
                field = await reader.next()
                if field is None:
                    return web.json_response({"error": "No file uploaded"}, status=400)
                
                package_data = await field.read()
            else:
                # Assume raw binary upload
                package_data = await request.read()
                
            if not package_data:
                return web.json_response({"error": "Empty package data"}, status=400)
                
            # Encode as base64 for tunnel transport
            package_b64 = base64.b64encode(package_data).decode("ascii")
            
            # Forward to local server
            request_body = json.dumps({"package": package_b64})
            response = await self.tunnel_server.send_request(
                "POST", "/api/v1/tts/voices/import", 
                body=request_body, timeout=120
            )
            
            return web.Response(
                text=response.body or "{}",
                status=response.status_code,
                content_type="application/json"
            )
            
        except Exception as e:
            logger.exception("Error importing voice package")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_sync_packages(self, request: web.Request) -> web.Response:
        """POST /api/v1/tts/voices/sync — sync all voices from GPU server to relay."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error

        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error

        try:
            # Forward sync request to local server
            response = await self.tunnel_server.send_request(
                "POST", "/api/v1/tts/voices/sync", 
                timeout=300  # Extended timeout for bulk export
            )
            
            if response.status_code != 200:
                return web.Response(
                    text=response.body or "{}",
                    status=response.status_code,
                    content_type="application/json"
                )
                
            # Parse response with all packages
            data = json.loads(response.body or "{}")
            packages = data.get("packages", {})
            
            # Store packages locally (in memory for now, could persist to disk)
            # This is where you might save packages to local storage on the relay
            logger.info(f"Received {len(packages)} voice packages from GPU server")
            
            return web.json_response({
                "synced": len(packages),
                "voices": list(packages.keys())
            })
            
        except Exception as e:
            logger.exception("Error syncing voice packages")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_websocket_tunnel(self, request: web.Request) -> web.WebSocketResponse:
        """WebSocket endpoint for tunnel connections from local GPU machines."""
        ws = web.WebSocketResponse(max_msg_size=50 * 1024 * 1024)
        await ws.prepare(request)

        debug_event("tunnel_connect", remote=request.remote)
        logger.info("New WebSocket tunnel connection from %s", request.remote)

        # Wrap aiohttp WebSocket to match websockets interface
        adapter = AioHTTPWebSocketAdapter(ws)
        await self.tunnel_server.handle_connection(adapter)

        debug_event("tunnel_disconnect", remote=request.remote)
        return ws

    async def handle_debug_ws(self, request: web.Request) -> web.WebSocketResponse:
        """WebSocket endpoint for live debug events."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Send recent history
        for entry in _debug_log:
            try:
                await ws.send_json(entry)
            except Exception:
                break

        _debug_subscribers.add(ws)
        try:
            async for msg in ws:
                pass  # Just keep connection alive
        finally:
            _debug_subscribers.discard(ws)
        return ws

    async def handle_debug_http(self, request: web.Request) -> web.Response:
        """GET /api/v1/debug — recent debug events as JSON."""
        import resource
        mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KB→MB
        return web.json_response({
            "mem_rss_mb": round(mem_mb, 1),
            "tunnel_connected": self.tunnel_server.has_client,
            "pending_requests": len(self.tunnel_server._pending_requests),
            "uptime_seconds": round(time.time() - self.start_time, 1),
            "recent_events": list(_debug_log)[-50:],
        })

    # ── Clone Prompt Endpoints (forwarded to local server) ──────────

    async def handle_voice_design(self, request: web.Request) -> web.Response:
        """POST /api/v1/voices/design — generate reference clip."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error
        body = await request.text()
        return await self._forward_with_fallback("POST", "/api/v1/voices/design", body=body)

    async def handle_create_clone_prompt(self, request: web.Request) -> web.Response:
        """POST /api/v1/voices/clone-prompt — create persistent clone prompt."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error
        body = await request.text()
        return await self._forward_with_fallback("POST", "/api/v1/voices/clone-prompt", body=body)

    async def handle_list_prompts(self, request: web.Request) -> web.Response:
        """GET /api/v1/voices/prompts — list saved clone prompts."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error
        # Forward query string
        path = "/api/v1/voices/prompts"
        if request.query_string:
            path += f"?{request.query_string}"
        return await self._forward_to_local("GET", path)

    async def handle_search_prompts(self, request: web.Request) -> web.Response:
        """GET /api/v1/voices/prompts/search — search prompts by voice library fields."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error
        path = "/api/v1/voices/prompts/search"
        if request.query_string:
            path += f"?{request.query_string}"
        return await self._forward_to_local("GET", path)

    async def handle_list_characters(self, request: web.Request) -> web.Response:
        """GET /api/v1/voices/characters — list characters in voice library."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error
        return await self._forward_to_local("GET", "/api/v1/voices/characters")

    async def handle_delete_prompt(self, request: web.Request) -> web.Response:
        """DELETE /api/v1/voices/prompts/{name} — delete a clone prompt."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error
        name = request.match_info["name"]
        return await self._forward_to_local("DELETE", f"/api/v1/voices/prompts/{name}")

    async def handle_synthesize_with_prompt(self, request: web.Request) -> web.Response:
        """POST /api/v1/tts/clone-prompt — synthesize with saved clone prompt."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error
        body = await request.text()
        return await self._forward_with_fallback("POST", "/api/v1/tts/clone-prompt", body=body)

    async def handle_list_emotions(self, request: web.Request) -> web.Response:
        """GET /api/v1/voices/emotions — list emotion presets."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error
        return await self._forward_to_local("GET", "/api/v1/voices/emotions")

    async def handle_cast_voice(self, request: web.Request) -> web.Response:
        """POST /api/v1/voices/cast — full emotion casting for a character."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error
        body = await request.text()
        return await self._forward_with_fallback("POST", "/api/v1/voices/cast", body=body)

    async def handle_normalize(self, request: web.Request) -> web.Response:
        """POST /api/v1/audio/normalize — formant normalization."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error
        body = await request.text()
        return await self._forward_with_fallback("POST", "/api/v1/audio/normalize", body=body)

    async def handle_batch_design(self, request: web.Request) -> web.Response:
        """POST /api/v1/voices/design/batch — batch generate reference clips."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error
        body = await request.text()
        # Batch operations can be slow — use extended timeout
        return await self._forward_with_fallback("POST", "/api/v1/voices/design/batch", body=body)

    async def handle_batch_clone_prompt(self, request: web.Request) -> web.Response:
        """POST /api/v1/voices/clone-prompt/batch — batch create clone prompts."""
        auth_error = await self._require_auth(request)
        if auth_error:
            return auth_error
        tunnel_error = await self._require_tunnel()
        if tunnel_error:
            return tunnel_error
        body = await request.text()
        return await self._forward_with_fallback("POST", "/api/v1/voices/clone-prompt/batch", body=body)

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
        
        # Voice package routes
        app.router.add_get("/api/v1/tts/voices/{voice_id}/package", self.handle_export_package)
        app.router.add_post("/api/v1/tts/voices/import", self.handle_import_package)
        app.router.add_post("/api/v1/tts/voices/sync", self.handle_sync_packages)

        # Audio processing
        app.router.add_post("/api/v1/audio/normalize", self.handle_normalize)

        # Clone prompt routes
        app.router.add_get("/api/v1/voices/emotions", self.handle_list_emotions)
        app.router.add_post("/api/v1/voices/cast", self.handle_cast_voice)
        app.router.add_post("/api/v1/voices/design", self.handle_voice_design)
        app.router.add_post("/api/v1/voices/design/batch", self.handle_batch_design)
        app.router.add_post("/api/v1/voices/clone-prompt/batch", self.handle_batch_clone_prompt)
        app.router.add_post("/api/v1/voices/clone-prompt", self.handle_create_clone_prompt)
        app.router.add_get("/api/v1/voices/prompts/search", self.handle_search_prompts)
        app.router.add_get("/api/v1/voices/characters", self.handle_list_characters)
        app.router.add_get("/api/v1/voices/prompts", self.handle_list_prompts)
        app.router.add_delete("/api/v1/voices/prompts/{name}", self.handle_delete_prompt)
        app.router.add_post("/api/v1/tts/clone-prompt", self.handle_synthesize_with_prompt)

        # WebSocket tunnel endpoint
        app.router.add_get("/ws/tunnel", self.handle_websocket_tunnel)

        # Debug endpoints (no auth required — internal use)
        app.router.add_get("/ws/debug", self.handle_debug_ws)
        app.router.add_get("/api/v1/debug", self.handle_debug_http)

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

    @property
    def closed(self) -> bool:
        """Whether the connection is closed."""
        return self._closed or self._ws.closed

    async def recv(self) -> str:
        """Receive a message."""
        if self._receive_task is None:
            self._receive_task = asyncio.create_task(self._start_receiving())
            # Give the receiving task a moment to start
            await asyncio.sleep(0.001)

        if self._closed and self._queue.empty():
            raise ConnectionError("WebSocket closed")

        # Don't wait forever — check periodically if connection died
        while True:
            try:
                return await asyncio.wait_for(self._queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                if self._closed or self._ws.closed:
                    raise ConnectionError("WebSocket closed")
                continue

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
