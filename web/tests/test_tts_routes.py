"""Tests for TTS proxy routes — /api/v1/tts/*.

All relay calls are mocked via monkeypatching tts_proxy functions.
"""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROXY_MODULE = "web.app.services.tts_proxy"


def mock_tts_get(return_value):
    return patch(f"{PROXY_MODULE}.tts_get", new_callable=AsyncMock, return_value=return_value)


def mock_tts_post(return_value):
    return patch(f"{PROXY_MODULE}.tts_post", new_callable=AsyncMock, return_value=return_value)


def mock_tts_delete(return_value):
    return patch(f"{PROXY_MODULE}.tts_delete", new_callable=AsyncMock, return_value=return_value)


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/tts/status")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_design_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/tts/voices/design", json={"text": "hi", "instruct": "deep"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_synthesize_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/tts/synthesize", json={"voice_prompt": "x", "text": "hi"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET proxies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_proxies_to_relay(client: AsyncClient, auth_headers: dict):
    # Proxy must call /api/v1/tts/status (the frontend-designed endpoint that
    # returns runpod_configured/runpod_available). Calling the older /api/v1/status
    # omitted those fields before commit 530c0c2, causing "No GPU Backend" even
    # when RunPod was configured.
    relay_payload = {
        "status": "ok",
        "tunnel_connected": False,
        "models_loaded": [],
        "prompts_count": 0,
        "runpod_configured": True,
        "runpod_available": True,
    }
    with mock_tts_get(relay_payload) as m:
        resp = await client.get("/api/v1/tts/status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["runpod_configured"] is True
    assert body["runpod_available"] is True
    m.assert_called_once_with("/api/v1/tts/status")


@pytest.mark.asyncio
async def test_status_degraded_when_relay_unreachable(client: AsyncClient, auth_headers: dict):
    """When relay is down, status returns degraded response with runpod_configured=False.

    This ensures the frontend shows 'No GPU Backend' (not an unhandled error)
    and doesn't incorrectly imply RunPod is configured when the relay is
    unreachable (fixing the missing runpod_configured key in the error fallback).
    """
    from web.app.services.tts_proxy import TTSRelayError

    error = TTSRelayError(502, "Cannot connect to TTS relay — server may be down")
    with patch(f"{PROXY_MODULE}.tts_get", new_callable=AsyncMock, side_effect=error):
        resp = await client.get("/api/v1/tts/status", headers=auth_headers)

    assert resp.status_code == 200  # status endpoint never returns 5xx — returns degraded payload
    body = resp.json()
    assert body["status"] == "error"
    assert body["tunnel_connected"] is False
    assert body["runpod_configured"] is False   # must be present so frontend shows "No GPU Backend"
    assert body["runpod_available"] is False
    assert "error" in body


@pytest.mark.asyncio
async def test_list_characters(client: AsyncClient, auth_headers: dict):
    with mock_tts_get({"characters": ["kira", "marcus"]}) as m:
        resp = await client.get("/api/v1/tts/voices/characters", headers=auth_headers)
    assert resp.status_code == 200
    assert "kira" in resp.json()["characters"]
    m.assert_called_once_with("/api/v1/voices/characters")


@pytest.mark.asyncio
async def test_list_emotions(client: AsyncClient, auth_headers: dict):
    with mock_tts_get({"emotions": [], "modes": []}) as m:
        resp = await client.get("/api/v1/tts/voices/emotions", headers=auth_headers)
    assert resp.status_code == 200
    m.assert_called_once_with("/api/v1/voices/emotions")


@pytest.mark.asyncio
async def test_list_prompts_no_filter(client: AsyncClient, auth_headers: dict):
    with mock_tts_get({"prompts": []}) as m:
        resp = await client.get("/api/v1/tts/voices/prompts", headers=auth_headers)
    assert resp.status_code == 200
    m.assert_called_once_with("/api/v1/voices/prompts")


@pytest.mark.asyncio
async def test_list_prompts_with_tags(client: AsyncClient, auth_headers: dict):
    with mock_tts_get({"prompts": []}) as m:
        resp = await client.get("/api/v1/tts/voices/prompts?tags=kira", headers=auth_headers)
    assert resp.status_code == 200
    m.assert_called_once_with("/api/v1/voices/prompts?tags=kira")


@pytest.mark.asyncio
async def test_search_prompts(client: AsyncClient, auth_headers: dict):
    with mock_tts_get({"prompts": []}) as m:
        resp = await client.get(
            "/api/v1/tts/voices/prompts/search?character=kira&emotion=joy",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    call_path = m.call_args[0][0]
    assert "character=kira" in call_path
    assert "emotion=joy" in call_path


# ---------------------------------------------------------------------------
# POST proxies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_design_voice(client: AsyncClient, auth_headers: dict):
    with mock_tts_post({"audio": "base64data", "duration": 2.5}) as m:
        resp = await client.post(
            "/api/v1/tts/voices/design",
            json={"text": "Hello world", "instruct": "Deep male voice"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert resp.json()["audio"] == "base64data"
    m.assert_called_once()
    call_body = m.call_args[0][1]
    assert call_body["text"] == "Hello world"


@pytest.mark.asyncio
async def test_cast_voice(client: AsyncClient, auth_headers: dict):
    with mock_tts_post({"results": []}) as m:
        resp = await client.post(
            "/api/v1/tts/voices/cast",
            json={"character": "kira", "description": "husky woman"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    m.assert_called_once()


@pytest.mark.asyncio
async def test_synthesize(client: AsyncClient, auth_headers: dict):
    with mock_tts_post({"audio": "b64", "duration": 1.0}) as m:
        resp = await client.post(
            "/api/v1/tts/synthesize",
            json={"voice_prompt": "kira_joy_medium", "text": "Hello"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    m.assert_called_once()
    assert m.call_args[0][0] == "/api/v1/tts/clone-prompt"


@pytest.mark.asyncio
async def test_batch_design(client: AsyncClient, auth_headers: dict):
    with mock_tts_post({"results": [{"name": "test", "status": "ok"}]}) as m:
        resp = await client.post(
            "/api/v1/tts/voices/design/batch",
            json={"items": [{"name": "t", "text": "hi", "instruct": "deep"}]},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    m.assert_called_once()


@pytest.mark.asyncio
async def test_create_clone_prompt(client: AsyncClient, auth_headers: dict):
    with mock_tts_post({"name": "kira_base", "status": "created"}) as m:
        resp = await client.post(
            "/api/v1/tts/voices/clone-prompt",
            json={"audio": "base64audio", "name": "kira_base"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    m.assert_called_once()


@pytest.mark.asyncio
async def test_normalize_audio(client: AsyncClient, auth_headers: dict):
    with mock_tts_post({"audio": "normalized_b64"}) as m:
        resp = await client.post(
            "/api/v1/tts/audio/normalize",
            json={"audio": "b64in", "ref_audio": "b64ref"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    m.assert_called_once()


# ---------------------------------------------------------------------------
# DELETE proxies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_prompt(client: AsyncClient, auth_headers: dict):
    with mock_tts_delete({"deleted": True}) as m:
        resp = await client.delete("/api/v1/tts/voices/prompts/kira_joy_medium", headers=auth_headers)
    assert resp.status_code == 200
    m.assert_called_once_with("/api/v1/voices/prompts/kira_joy_medium")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_package_not_implemented(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/v1/tts/voices/import", headers=auth_headers)
    assert resp.status_code == 501


# ---------------------------------------------------------------------------
# tts_proxy.tts_post — fix/play-500-error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tts_post_raises_502_on_binary_response(client: AsyncClient, auth_headers: dict):
    """tts_proxy.tts_post must raise TTSRelayError(502), not JSONDecodeError,
    when the relay returns an unexpected binary/non-JSON response.

    This prevents a raw JSONDecodeError from bubbling up as HTTP 500.
    The fix wraps resp.json() in a try/except and surfaces a clear 502.
    """
    from web.app.services.tts_proxy import TTSRelayError, tts_post
    import httpx

    binary_content = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
    fake_resp = httpx.Response(
        status_code=200,
        headers={"content-type": "audio/wav"},
        content=binary_content,
        request=httpx.Request("POST", "http://localhost:9800/api/v1/tts/clone-prompt"),
    )

    with patch(f"{PROXY_MODULE}._get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=fake_resp)
        mock_get_client.return_value = mock_client

        with pytest.raises(TTSRelayError) as exc_info:
            await tts_post("/api/v1/tts/clone-prompt", {"voice_prompt": "kira", "text": "Hi"})

    assert exc_info.value.status_code == 502
    assert "audio/wav" in exc_info.value.detail or "binary" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_synthesize_returns_503_when_relay_returns_tunnel_required(
    client: AsyncClient, auth_headers: dict
):
    """POST /api/v1/tts/synthesize should surface 503 with clear message
    when the relay returns 503 tunnel_required (tunnel offline).
    """
    from web.app.services.tts_proxy import TTSRelayError

    with patch(f"{PROXY_MODULE}.tts_post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = TTSRelayError(
            503,
            "Clone-prompt synthesis requires the local GPU to be connected. "
            "Daniel's GPU tunnel is currently offline.",
        )
        resp = await client.post(
            "/api/v1/tts/synthesize",
            json={"voice_prompt": "kira_joy_medium", "text": "Hello"},
            headers=auth_headers,
        )

    assert resp.status_code == 503
    body = resp.json()
    assert "tunnel" in body["detail"].lower() or "GPU" in body["detail"]
