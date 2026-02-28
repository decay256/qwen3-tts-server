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
    with mock_tts_get({"status": "ok", "tunnel": True}) as m:
        resp = await client.get("/api/v1/tts/status", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    m.assert_called_once_with("/api/v1/status")


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
