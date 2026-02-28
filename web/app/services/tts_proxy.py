"""TTS relay proxy — forwards requests to the GPU relay server."""

import logging
from typing import Any

import httpx

from web.app.core.config import settings

logger = logging.getLogger(__name__)

# Reusable async client
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.tts_relay_url,
            headers={"Authorization": f"Bearer {settings.tts_relay_api_key}"},
            timeout=600.0,  # long timeout for batch operations
        )
    return _client


class TTSRelayError(Exception):
    """Error from TTS relay with status code and detail."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _handle_error(resp: httpx.Response) -> None:
    """Raise TTSRelayError with useful details on non-2xx responses."""
    if resp.is_success:
        return
    try:
        body = resp.json()
        detail = body.get("detail", body.get("error", str(body)))
    except Exception:
        detail = resp.text[:500] if resp.text else f"HTTP {resp.status_code}"

    logger.warning("TTS relay error: %s %s → %d: %s", resp.request.method, resp.request.url, resp.status_code, detail)
    raise TTSRelayError(resp.status_code, detail)


async def tts_get(path: str, params: dict | None = None) -> dict:
    """GET request to TTS relay."""
    try:
        client = _get_client()
        resp = await client.get(path, params=params)
        _handle_error(resp)
        return resp.json()
    except httpx.ConnectError:
        raise TTSRelayError(502, "Cannot connect to TTS relay — server may be down")
    except httpx.TimeoutException:
        raise TTSRelayError(504, "TTS relay timed out — GPU may be cold-starting")


async def tts_post(path: str, body: dict | None = None) -> dict:
    """POST request to TTS relay."""
    try:
        client = _get_client()
        resp = await client.post(path, json=body)
        _handle_error(resp)
        return resp.json()
    except httpx.ConnectError:
        raise TTSRelayError(502, "Cannot connect to TTS relay — server may be down")
    except httpx.TimeoutException:
        raise TTSRelayError(504, "TTS relay timed out — GPU may be cold-starting")


async def tts_delete(path: str) -> dict:
    """DELETE request to TTS relay."""
    try:
        client = _get_client()
        resp = await client.delete(path)
        _handle_error(resp)
        return resp.json()
    except httpx.ConnectError:
        raise TTSRelayError(502, "Cannot connect to TTS relay — server may be down")
    except httpx.TimeoutException:
        raise TTSRelayError(504, "TTS relay timed out — GPU may be cold-starting")


async def close_client() -> None:
    """Close the httpx client on shutdown."""
    global _client
    if _client:
        await _client.aclose()
        _client = None
