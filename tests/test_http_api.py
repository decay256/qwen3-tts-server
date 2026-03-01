"""Tests for the remote relay HTTP API routes using aiohttp test client."""

import asyncio
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web


@pytest.fixture
def relay_config():
    return {
        "api_key": "test-api-key",
        "remote": {"bind": "127.0.0.1", "port": 9800},
    }


@pytest.fixture
def relay(relay_config):
    from server.remote_relay import RemoteRelay
    return RemoteRelay(relay_config)


@pytest_asyncio.fixture
async def client(relay):
    app = relay.create_app()
    async with TestClient(TestServer(app)) as c:
        yield c


def auth_headers():
    return {"Authorization": "Bearer test-api-key"}


@pytest.mark.asyncio
async def test_status_no_auth(client):
    resp = await client.get("/api/v1/status")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_status_with_auth(client, relay):
    resp = await client.get("/api/v1/status", headers=auth_headers())
    assert resp.status == 200
    data = await resp.json()
    assert data["relay"] == "ok"
    assert data["tunnel_connected"] is False


@pytest.mark.asyncio
async def test_voices_no_tunnel(client):
    resp = await client.get("/api/v1/tts/voices", headers=auth_headers())
    assert resp.status == 503


@pytest.mark.asyncio
async def test_synthesize_no_tunnel(client):
    resp = await client.post(
        "/api/v1/tts/synthesize",
        json={"text": "hello", "voice_id": "test"},
        headers=auth_headers(),
    )
    assert resp.status == 503


@pytest.mark.asyncio
async def test_synthesize_no_auth(client):
    resp = await client.post(
        "/api/v1/tts/synthesize",
        json={"text": "hello", "voice_id": "test"},
    )
    assert resp.status == 401


@pytest.mark.asyncio
async def test_design_no_tunnel(client):
    resp = await client.post(
        "/api/v1/tts/design",
        json={"description": "deep male voice"},
        headers=auth_headers(),
    )
    assert resp.status == 503


@pytest.mark.asyncio
async def test_clone_no_tunnel(client):
    resp = await client.post(
        "/api/v1/tts/clone",
        json={"voice_name": "test", "reference_audio": "base64data"},
        headers=auth_headers(),
    )
    assert resp.status == 503


@pytest.mark.asyncio
async def test_synthesize_forwarded(client, relay):
    """Test that synthesize forwards through tunnel when connected."""
    from server.tunnel import TunnelMessage, MessageType

    mock_response = TunnelMessage(
        type=MessageType.RESPONSE,
        body=json.dumps({"audio": "dGVzdA==", "format": "wav", "sample_rate": 24000}),
        body_binary=True,
        headers={"Content-Type": "application/json"},
    )
    relay.tunnel_server.send_request = AsyncMock(return_value=mock_response)
    relay.tunnel_server._clients["fake"] = MagicMock()

    resp = await client.post(
        "/api/v1/tts/synthesize",
        json={"text": "hello", "voice_id": "narrator"},
        headers=auth_headers(),
    )
    assert resp.status == 200
    assert resp.content_type == "audio/wav"


@pytest.mark.asyncio
async def test_voices_forwarded(client, relay):
    from server.tunnel import TunnelMessage, MessageType

    mock_response = TunnelMessage(
        type=MessageType.RESPONSE,
        body=json.dumps({"voices": [{"voice_id": "v1", "name": "Test", "type": "designed"}]}),
        headers={"Content-Type": "application/json"},
    )
    relay.tunnel_server.send_request = AsyncMock(return_value=mock_response)
    relay.tunnel_server._clients["fake"] = MagicMock()

    resp = await client.get("/api/v1/tts/voices", headers=auth_headers())
    assert resp.status == 200
    data = json.loads(await resp.text())
    assert "voices" in data


@pytest.mark.asyncio
async def test_timeout_returns_504(client, relay):
    relay.tunnel_server.send_request = AsyncMock(side_effect=TimeoutError("timeout"))
    relay.tunnel_server._clients["fake"] = MagicMock()

    resp = await client.post(
        "/api/v1/tts/synthesize",
        json={"text": "hello", "voice_id": "test"},
        headers=auth_headers(),
    )
    assert resp.status == 504


@pytest.mark.asyncio
async def test_connection_error_returns_503(client, relay):
    relay.tunnel_server.send_request = AsyncMock(side_effect=ConnectionError("disconnected"))
    relay.tunnel_server._clients["fake"] = MagicMock()

    resp = await client.post(
        "/api/v1/tts/synthesize",
        json={"text": "hello", "voice_id": "test"},
        headers=auth_headers(),
    )
    assert resp.status == 503


# ---------------------------------------------------------------------------
# Clone-prompt synthesis — fix/play-500-error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_prompt_synth_no_tunnel_returns_503(client, relay):
    """POST /api/v1/tts/clone-prompt must return 503 (not 500) when tunnel
    is disconnected, even if RunPod is configured as fallback.

    Clone-prompt synthesis requires .pt files that live only on the local GPU
    machine.  RunPod workers start with an empty voice-prompts directory and
    cannot serve this endpoint.
    """
    assert not relay.tunnel_server.has_client

    resp = await client.post(
        "/api/v1/tts/clone-prompt",
        json={"voice_prompt": "kira_joy_medium", "text": "Hello world", "format": "wav"},
        headers=auth_headers(),
    )
    assert resp.status == 503
    data = await resp.json()
    assert "tunnel" in data["error"].lower() or data.get("code") == "tunnel_required"


@pytest.mark.asyncio
async def test_clone_prompt_synth_no_tunnel_with_runpod_configured_returns_503(relay_config):
    """Even when RunPod is configured, clone-prompt synthesis must return 503
    when the tunnel is not connected (RunPod fallback is not valid here).
    """
    from unittest.mock import AsyncMock, patch

    cfg = dict(relay_config)
    cfg["runpod"] = {"endpoint_id": "fake-ep", "api_key": "fake-rp-key"}
    with patch("server.remote_relay.RunPodClient") as MockRPC:
        MockRPC.return_value = AsyncMock()
        from server.remote_relay import RemoteRelay
        relay_with_runpod = RemoteRelay(cfg)

    app = relay_with_runpod.create_app()
    async with TestClient(TestServer(app)) as c:
        resp = await c.post(
            "/api/v1/tts/clone-prompt",
            json={"voice_prompt": "kira_joy_medium", "text": "Hello", "format": "wav"},
            headers=auth_headers(),
        )
        assert resp.status == 503
        data = await resp.json()
        assert data.get("code") == "tunnel_required"


@pytest.mark.asyncio
async def test_clone_prompt_synth_with_tunnel_forwards_request(client, relay):
    """POST /api/v1/tts/clone-prompt forwards to local server when tunnel is connected."""
    from server.tunnel import TunnelMessage, MessageType

    mock_response = TunnelMessage(
        type=MessageType.RESPONSE,
        body=json.dumps({"audio": "dGVzdA==", "format": "wav", "sample_rate": 24000, "duration_s": 0.5}),
        headers={"Content-Type": "application/json"},
    )
    relay.tunnel_server.send_request = AsyncMock(return_value=mock_response)
    relay.tunnel_server._clients["fake"] = MagicMock()

    resp = await client.post(
        "/api/v1/tts/clone-prompt",
        json={"voice_prompt": "kira_joy_medium", "text": "Hello", "format": "wav"},
        headers=auth_headers(),
    )
    assert resp.status == 200


@pytest.mark.asyncio
async def test_forward_to_runpod_returns_422_on_error_output(relay):
    """_forward_to_runpod must return HTTP 422 (not 200) when RunPod COMPLETES
    a job but the output contains an 'error' key.
    """
    from unittest.mock import AsyncMock

    relay.runpod = AsyncMock()
    relay.runpod.runsync = AsyncMock(return_value={
        "status": "COMPLETED",
        "output": {"error": "Prompt 'kira_joy_medium' not found"},
    })

    resp = await relay._forward_to_runpod("/api/v1/tts/clone-prompt", {"voice_prompt": "kira_joy_medium"})
    assert resp.status == 422
    import json as _json
    body = _json.loads(resp.body)
    assert "error" in body
    assert "kira_joy_medium" in body["error"]


@pytest.mark.asyncio
async def test_forward_to_runpod_returns_json_not_binary_on_audio(relay):
    """_forward_to_runpod must return JSON with base64 audio (not raw binary bytes)
    so that tts_proxy.tts_post can parse the response without hitting a
    JSONDecodeError (the root-cause 500 bug).
    """
    import base64
    from unittest.mock import AsyncMock

    fake_audio_b64 = base64.b64encode(b"RIFF\x00\x00\x00\x00WAVEfmt ").decode()
    relay.runpod = AsyncMock()
    relay.runpod.runsync = AsyncMock(return_value={
        "status": "COMPLETED",
        "output": {"audio": fake_audio_b64, "format": "wav", "duration_s": 1.0},
    })

    resp = await relay._forward_to_runpod("/api/v1/voices/design", {"text": "hi", "instruct": "deep"})
    assert resp.status == 200
    import json as _json
    body = _json.loads(resp.body)
    assert "audio" in body
    assert body["audio"] == fake_audio_b64
    assert body["format"] == "wav"
    assert "json" in resp.content_type

# ---------------------------------------------------------------------------
# /api/v1/status — RunPod fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_no_runpod_configured(client):
    """status returns runpod_configured=False when RunPod not set up."""
    resp = await client.get("/api/v1/status", headers=auth_headers())
    assert resp.status == 200
    data = await resp.json()
    assert data["runpod_configured"] is False
    assert data["runpod_available"] is False
    assert "runpod_health" not in data


@pytest.mark.asyncio
async def test_status_with_runpod_configured(relay):
    """status includes RunPod health info when RunPod is configured."""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_runpod = MagicMock()
    mock_runpod.health = AsyncMock(return_value={"workers": {"idle": 2, "ready": 1}})
    relay.runpod = mock_runpod

    app = relay.create_app()
    async with TestClient(TestServer(app)) as c:
        resp = await c.get("/api/v1/status", headers=auth_headers())
        data = await resp.json()

    assert data["runpod_configured"] is True
    assert data["runpod_available"] is True
    assert data["runpod_health"] == {"workers": {"idle": 2, "ready": 1}}


@pytest.mark.asyncio
async def test_status_runpod_no_workers(relay):
    """runpod_available=False when health check returns zero workers."""
    from unittest.mock import AsyncMock, MagicMock

    mock_runpod = MagicMock()
    mock_runpod.health = AsyncMock(return_value={"workers": {"idle": 0, "ready": 0}})
    relay.runpod = mock_runpod

    app = relay.create_app()
    async with TestClient(TestServer(app)) as c:
        resp = await c.get("/api/v1/status", headers=auth_headers())
        data = await resp.json()

    assert data["runpod_configured"] is True
    assert data["runpod_available"] is False


@pytest.mark.asyncio
async def test_status_runpod_health_check_fails(relay):
    """runpod_available=False and error info returned when health check raises."""
    from unittest.mock import AsyncMock, MagicMock
    import aiohttp

    mock_runpod = MagicMock()
    mock_runpod.health = AsyncMock(side_effect=Exception("Connection refused"))
    relay.runpod = mock_runpod

    app = relay.create_app()
    async with TestClient(TestServer(app)) as c:
        resp = await c.get("/api/v1/status", headers=auth_headers())
        data = await resp.json()

    assert data["runpod_configured"] is True
    assert data["runpod_available"] is False
    assert "error" in data["runpod_health"]


# ---------------------------------------------------------------------------
# /api/v1/tts/status — frontend combined status endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tts_status_no_auth(client):
    resp = await client.get("/api/v1/tts/status")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_tts_status_no_tunnel_no_runpod(client):
    """tts/status returns disconnected state when no tunnel or RunPod."""
    resp = await client.get("/api/v1/tts/status", headers=auth_headers())
    assert resp.status == 200
    data = await resp.json()
    assert data["tunnel_connected"] is False
    assert data["runpod_configured"] is False
    assert data["runpod_available"] is False
    assert data["models_loaded"] == []
    assert data["prompts_count"] == 0


@pytest.mark.asyncio
async def test_tts_status_with_runpod_available(relay):
    """tts/status returns runpod_available=True when workers are up."""
    from unittest.mock import AsyncMock, MagicMock

    mock_runpod = MagicMock()
    mock_runpod.health = AsyncMock(return_value={"workers": {"ready": 3, "idle": 1}})
    relay.runpod = mock_runpod

    app = relay.create_app()
    async with TestClient(TestServer(app)) as c:
        resp = await c.get("/api/v1/tts/status", headers=auth_headers())
        data = await resp.json()

    assert data["runpod_configured"] is True
    assert data["runpod_available"] is True
    assert data["tunnel_connected"] is False


@pytest.mark.asyncio
async def test_tts_status_with_tunnel_merges_local(relay):
    """tts/status merges models_loaded and prompts_count from local when tunnel connected."""
    from unittest.mock import AsyncMock, MagicMock
    from server.tunnel import TunnelMessage, MessageType

    local_status = {
        "status": "ok",
        "models_loaded": ["qwen3-tts-0.5b"],
        "prompts_count": 42,
    }
    mock_response = TunnelMessage(
        type=MessageType.RESPONSE,
        body=json.dumps(local_status),
        headers={"Content-Type": "application/json"},
    )
    relay.tunnel_server.send_request = AsyncMock(return_value=mock_response)
    relay.tunnel_server._clients["fake"] = MagicMock()

    app = relay.create_app()
    async with TestClient(TestServer(app)) as c:
        resp = await c.get("/api/v1/tts/status", headers=auth_headers())
        data = await resp.json()

    assert data["tunnel_connected"] is True
    assert data["models_loaded"] == ["qwen3-tts-0.5b"]
    assert data["prompts_count"] == 42


@pytest.mark.asyncio
async def test_tts_status_tunnel_error_returns_local_error(relay):
    """tts/status includes local_error when local server call fails."""
    from unittest.mock import AsyncMock, MagicMock

    relay.tunnel_server.send_request = AsyncMock(side_effect=Exception("tunnel broken"))
    relay.tunnel_server._clients["fake"] = MagicMock()

    app = relay.create_app()
    async with TestClient(TestServer(app)) as c:
        resp = await c.get("/api/v1/tts/status", headers=auth_headers())
        data = await resp.json()

    assert data["tunnel_connected"] is True
    assert "local_error" in data
    assert "tunnel broken" in data["local_error"]


@pytest.mark.asyncio
async def test_tts_status_runpod_health_timeout(relay):
    """tts/status handles RunPod health timeout gracefully."""
    from unittest.mock import AsyncMock, MagicMock

    async def slow_health():
        await asyncio.sleep(10)

    mock_runpod = MagicMock()
    mock_runpod.health = slow_health
    relay.runpod = mock_runpod

    app = relay.create_app()
    async with TestClient(TestServer(app)) as c:
        resp = await c.get("/api/v1/tts/status", headers=auth_headers())
        data = await resp.json()

    assert data["runpod_available"] is False
    assert "error" in data.get("runpod_health", {})
