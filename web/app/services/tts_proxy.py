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


async def tts_get(path: str, params: dict | None = None) -> dict:
    """GET request to TTS relay.

    Args:
        path: API path (e.g., "/api/v1/voices/characters").
        params: Query parameters.

    Returns:
        Parsed JSON response.

    Raises:
        httpx.HTTPStatusError: On non-2xx response.
    """
    client = _get_client()
    resp = await client.get(path, params=params)
    resp.raise_for_status()
    return resp.json()


async def tts_post(path: str, body: dict | None = None) -> dict:
    """POST request to TTS relay.

    Args:
        path: API path.
        body: JSON body.

    Returns:
        Parsed JSON response.

    Raises:
        httpx.HTTPStatusError: On non-2xx response.
    """
    client = _get_client()
    resp = await client.post(path, json=body)
    resp.raise_for_status()
    return resp.json()


async def tts_delete(path: str) -> dict:
    """DELETE request to TTS relay."""
    client = _get_client()
    resp = await client.delete(path)
    resp.raise_for_status()
    return resp.json()


async def close_client() -> None:
    """Close the httpx client on shutdown."""
    global _client
    if _client:
        await _client.aclose()
        _client = None
