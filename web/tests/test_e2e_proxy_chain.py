"""End-to-end proxy chain tests — Issues #10 and #11.

Verifies the FULL request path:
  Frontend (CharacterPage) → web /api/v1/tts/voices/design
  → tts_proxy.tts_post → relay /api/v1/voices/design
  → RunPod handler → returns JSON with base64 audio
  → frontend AudioPlayer plays it

All relay calls are mocked so no real GPU or RunPod is required.
"""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

PROXY_MODULE = "web.app.services.tts_proxy"


# ---------------------------------------------------------------------------
# Issue #10 — Preview rendering via RunPod fallback (full path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_design_preview_full_chain_basic(client: AsyncClient, auth_headers: dict):
    """Frontend preview request flows correctly end-to-end.

    Simulates the exact payload CharacterPage sends for the ▶ Preview button:
      { text, instruct, format }
    and verifies the web proxy forwards the right body to the relay endpoint
    and returns audio+format to the caller.
    """
    relay_response = {
        "audio": "UklGRiQAAABXQVZFZm10IBAAAA==",  # minimal fake base64 WAV
        "format": "wav",
        "duration_s": 1.5,
        "sample_rate": 24000,
    }
    with patch(f"{PROXY_MODULE}.tts_post", new_callable=AsyncMock, return_value=relay_response) as mock_post:
        resp = await client.post(
            "/api/v1/tts/voices/design",
            json={
                "text": "Hello world",
                "instruct": "Adult woman, low pitch, husky voice",
                "format": "wav",
            },
            headers=auth_headers,
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()

    # Frontend AudioPlayer reads these two fields
    assert "audio" in body, "Response must include 'audio' field for AudioPlayer"
    assert body["audio"] == relay_response["audio"]
    assert body["format"] == "wav"

    # Verify relay was called with the correct endpoint path
    mock_post.assert_called_once()
    called_path = mock_post.call_args[0][0]
    assert called_path == "/api/v1/voices/design", (
        f"Relay endpoint mismatch: got '{called_path}', "
        "expected '/api/v1/voices/design'"
    )

    # Verify request body forwarded to relay
    called_body = mock_post.call_args[0][1]
    assert called_body["text"] == "Hello world"
    assert called_body["instruct"] == "Adult woman, low pitch, husky voice"
    assert called_body["format"] == "wav"


@pytest.mark.asyncio
async def test_design_preview_language_default(client: AsyncClient, auth_headers: dict):
    """language defaults to 'English' when not specified by frontend."""
    relay_response = {"audio": "base64audio==", "format": "wav", "duration_s": 1.0}
    with patch(f"{PROXY_MODULE}.tts_post", new_callable=AsyncMock, return_value=relay_response) as mock_post:
        resp = await client.post(
            "/api/v1/tts/voices/design",
            # Frontend omits language — relay default kicks in
            json={"text": "Test", "instruct": "Deep voice"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    called_body = mock_post.call_args[0][1]
    assert called_body.get("language") == "English", (
        "language must default to 'English' when not specified by frontend"
    )


@pytest.mark.asyncio
async def test_design_preview_relay_502_becomes_502(client: AsyncClient, auth_headers: dict):
    """Relay error surfaces as HTTP 502 with detail, not a raw 500."""
    from web.app.services.tts_proxy import TTSRelayError

    with patch(f"{PROXY_MODULE}.tts_post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = TTSRelayError(502, "RunPod error: worker crashed")
        resp = await client.post(
            "/api/v1/tts/voices/design",
            json={"text": "Hello", "instruct": "Deep voice"},
            headers=auth_headers,
        )
    assert resp.status_code == 502
    assert "RunPod" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_design_preview_relay_504_becomes_504(client: AsyncClient, auth_headers: dict):
    """504 timeout from relay propagates as 504."""
    from web.app.services.tts_proxy import TTSRelayError

    with patch(f"{PROXY_MODULE}.tts_post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = TTSRelayError(504, "TTS relay timed out — GPU may be cold-starting")
        resp = await client.post(
            "/api/v1/tts/voices/design",
            json={"text": "Hello", "instruct": "Deep voice"},
            headers=auth_headers,
        )
    assert resp.status_code == 504


# ---------------------------------------------------------------------------
# Issue #10 — Cast button: create_prompt/prompt_name/tags must pass through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cast_single_create_prompt_passes_through(client: AsyncClient, auth_headers: dict):
    """Cast button sends create_prompt/prompt_name/tags — all must reach the relay.

    Bug: DesignRequest model previously only had {text, instruct, language, format}.
    The extra fields were silently dropped by Pydantic, so the GPU never saved
    the clone prompt.  Fix: add optional create_prompt/prompt_name/tags to the model.
    """
    relay_response = {
        "audio": "UklGRiQAAABXQVZFZm10IBAAAA==",
        "format": "wav",
        "duration_s": 1.5,
        "name": "kira_joy_medium",   # GPU server returns the saved prompt name
    }
    cast_payload = {
        "text": "Joy is the word that comes to mind.",
        "instruct": "Middle-aged woman, slightly husky, warm, joyful and exuberant",
        "format": "wav",
        "create_prompt": True,
        "prompt_name": "kira_joy_medium",
        "tags": ["kira", "joy", "medium"],
    }
    with patch(f"{PROXY_MODULE}.tts_post", new_callable=AsyncMock, return_value=relay_response) as mock_post:
        resp = await client.post(
            "/api/v1/tts/voices/design",
            json=cast_payload,
            headers=auth_headers,
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    mock_post.assert_called_once()
    called_body = mock_post.call_args[0][1]

    # These are the critical fields that were previously dropped
    assert called_body.get("create_prompt") is True, (
        "create_prompt=True must be forwarded to relay (was being silently dropped)"
    )
    assert called_body.get("prompt_name") == "kira_joy_medium", (
        "prompt_name must be forwarded to relay (was being silently dropped)"
    )
    assert called_body.get("tags") == ["kira", "joy", "medium"], (
        "tags must be forwarded to relay (was being silently dropped)"
    )

    # Core fields still present
    assert called_body["text"] == cast_payload["text"]
    assert called_body["instruct"] == cast_payload["instruct"]


@pytest.mark.asyncio
async def test_cast_no_create_prompt_excludes_field(client: AsyncClient, auth_headers: dict):
    """When create_prompt is omitted, the relay body should not include it.

    Uses exclude_none=True so relay body stays clean for plain preview calls.
    """
    relay_response = {"audio": "base64audio==", "format": "wav", "duration_s": 1.0}
    with patch(f"{PROXY_MODULE}.tts_post", new_callable=AsyncMock, return_value=relay_response) as mock_post:
        resp = await client.post(
            "/api/v1/tts/voices/design",
            json={"text": "Hello", "instruct": "Deep voice", "format": "wav"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    called_body = mock_post.call_args[0][1]
    assert "create_prompt" not in called_body, "create_prompt should be absent for plain previews"
    assert "prompt_name" not in called_body, "prompt_name should be absent for plain previews"
    assert "tags" not in called_body, "tags should be absent for plain previews"


# ---------------------------------------------------------------------------
# Issue #11 — Relay route /api/v1/voices/design exists and uses fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relay_design_endpoint_correct_path(client: AsyncClient, auth_headers: dict):
    """Web proxy must call relay at /api/v1/voices/design (not /api/v1/tts/voices/design).

    The relay registers the route as POST /api/v1/voices/design.
    The web proxy must strip the /tts prefix before forwarding.
    """
    relay_response = {"audio": "testbase64==", "format": "wav", "duration_s": 0.5}
    with patch(f"{PROXY_MODULE}.tts_post", new_callable=AsyncMock, return_value=relay_response) as mock_post:
        resp = await client.post(
            "/api/v1/tts/voices/design",
            json={"text": "Test", "instruct": "Voice instruction"},
            headers=auth_headers,
        )
    assert resp.status_code == 200

    called_path = mock_post.call_args[0][0]
    # Web proxy route calls tts_proxy.tts_post("/api/v1/voices/design", ...)
    # NOT "/api/v1/tts/voices/design" — that would 404 on the relay
    assert called_path == "/api/v1/voices/design", (
        f"Relay endpoint mismatch: got '{called_path}'. "
        "Relay registers POST /api/v1/voices/design (no /tts prefix). "
        "Fix: web/app/routes/tts.py must call tts_proxy.tts_post('/api/v1/voices/design', ...)"
    )


# ---------------------------------------------------------------------------
# Full chain: request body transformation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_design_body_transformation_complete(client: AsyncClient, auth_headers: dict):
    """All fields transform correctly through the proxy chain.

    Frontend body → Pydantic validation → relay body:
    - text: str (required)
    - instruct: str (required)
    - language: str (default "English")
    - format: str (default "wav")
    - create_prompt: bool | None (optional, must pass-through if set)
    - prompt_name: str | None (optional, must pass-through if set)
    - tags: list[str] | None (optional, must pass-through if set)
    """
    relay_response = {"audio": "abc123==", "format": "wav", "duration_s": 2.0}
    frontend_payload = {
        "text": "She laughed softly.",
        "instruct": "Warm feminine voice, 35-year-old, slightly breathless",
        "language": "English",
        "format": "wav",
        "create_prompt": True,
        "prompt_name": "elena_base",
        "tags": ["elena", "neutral", "base"],
    }
    with patch(f"{PROXY_MODULE}.tts_post", new_callable=AsyncMock, return_value=relay_response) as mock_post:
        resp = await client.post(
            "/api/v1/tts/voices/design",
            json=frontend_payload,
            headers=auth_headers,
        )
    assert resp.status_code == 200
    called_body = mock_post.call_args[0][1]

    for field in ["text", "instruct", "language", "format", "create_prompt", "prompt_name", "tags"]:
        assert field in called_body, f"Field '{field}' missing from relay call body"
        assert called_body[field] == frontend_payload[field], (
            f"Field '{field}' value mismatch: got {called_body[field]!r}, "
            f"expected {frontend_payload[field]!r}"
        )
