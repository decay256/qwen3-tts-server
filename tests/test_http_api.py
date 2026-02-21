"""Tests for the remote relay HTTP API routes using aiohttp test client."""

import json
import pytest
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


@pytest.fixture
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
