"""Tests for LocalServer request handlers with mocked TTS engine."""

import asyncio
import base64
import json
from unittest.mock import MagicMock, patch, AsyncMock

import numpy as np
import pytest
import pytest_asyncio

from server.tunnel import TunnelMessage, MessageType


def make_request(path, method="POST", body=None):
    return TunnelMessage(
        type=MessageType.REQUEST,
        path=path,
        method=method,
        body=json.dumps(body) if body else None,
    )


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.is_loaded = True
    engine.get_health.return_value = {
        "gpu_name": "Test GPU",
        "vram_used_gb": 2.0,
        "vram_total_gb": 8.0,
        "loaded_models": ["voice_design", "base"],
    }
    # Return fake wav data (numpy array) and sample rate
    fake_wav = np.zeros(24000, dtype=np.float32)
    engine.generate_voice_design.return_value = (fake_wav, 24000)
    engine.generate_voice_clone.return_value = (fake_wav, 24000)
    engine.generate_custom_voice.return_value = (fake_wav, 24000)
    return engine


@pytest.fixture
def server(tmp_path, mock_engine):
    """Create a LocalServer with mocked engine and voice manager."""
    from server.voice_manager import VoiceManager
    from server.local_server import LocalServer

    config = {
        "api_key": "test-key",
        "remote": {"host": "localhost", "port": 9800},
        "local": {"voices_dir": str(tmp_path / "voices")},
    }

    mock_tunnel = MagicMock()
    mock_tunnel.get_status.return_value = {
        "connected": False,
        "state": "disconnected",
        "connection_count": 0,
        "health": {
            "total_attempts": 0,
            "successful_connections": 0,
            "consecutive_failures": 0,
            "success_rate": 0.0,
            "failure_types": {},
        },
        "circuit_breaker": {
            "active": False,
            "remaining_seconds": 0,
        },
    }

    with patch("server.local_server.TTSEngine", return_value=mock_engine):
        with patch("server.local_server.EnhancedTunnelClient", return_value=mock_tunnel):
            srv = LocalServer(config)
            srv.engine = mock_engine
            srv.voice_manager = VoiceManager(str(tmp_path / "voices"), engine=mock_engine)
            # Initialize test voices from config (no hardcoded novel characters)
            srv.voice_manager.initialize_voices_from_config({
                "narrator": {"description": "Deep male narrator voice"},
                "speaker1": {"description": "Young female voice"},
            })
            yield srv


@pytest.mark.asyncio
async def test_handle_status(server):
    req = make_request("/api/v1/status", method="GET")
    resp = await server._handle_request(req)
    assert resp.status_code == 200
    data = json.loads(resp.body)
    assert data["status"] == "ok"
    assert data["engine_ready"] is True
    assert data["voices_count"] == 2


@pytest.mark.asyncio
async def test_handle_list_voices(server):
    req = make_request("/api/v1/tts/voices", method="GET")
    resp = await server._handle_request(req)
    data = json.loads(resp.body)
    assert "voices" in data
    assert len(data["voices"]) == 2


@pytest.mark.asyncio
async def test_handle_design_returns_audio(server):
    req = make_request("/api/v1/tts/design", body={
        "text": "Hello world",
        "description": "Deep male voice",
    })
    with patch("server.tts_engine.wav_to_format", return_value=b"fake-audio"):
        resp = await server._handle_request(req)
    assert resp.status_code == 200
    data = json.loads(resp.body)
    assert "audio" in data
    audio_bytes = base64.b64decode(data["audio"])
    assert audio_bytes == b"fake-audio"
    assert data["format"] == "wav"
    assert data["description"] == "Deep male voice"


@pytest.mark.asyncio
async def test_handle_design_missing_text(server):
    req = make_request("/api/v1/tts/design", body={"description": "voice"})
    resp = await server._handle_request(req)
    assert resp.status_code == 400
    assert "text" in json.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_handle_design_missing_description(server):
    req = make_request("/api/v1/tts/design", body={"text": "hello"})
    resp = await server._handle_request(req)
    assert resp.status_code == 400
    assert "description" in json.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_handle_design_engine_not_loaded(server):
    server.engine.is_loaded = False
    req = make_request("/api/v1/tts/design", body={
        "text": "hello", "description": "voice",
    })
    resp = await server._handle_request(req)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_handle_synthesize_by_voice_name(server):
    """voice_name resolves to a voice and uses appropriate synthesis path."""
    # narrator should exist from initialize_voices_from_config
    req = make_request("/api/v1/tts/synthesize", body={
        "text": "Hello world",
        "voice_name": "narrator",
    })
    with patch("server.tts_engine.wav_to_format", return_value=b"audio-data"):
        resp = await server._handle_request(req)
    assert resp.status_code == 200
    data = json.loads(resp.body)
    assert "audio" in data


@pytest.mark.asyncio
async def test_handle_synthesize_by_voice_id(server):
    """voice_id fallback when voice_name not provided."""
    voices = server.voice_manager.list_voices()
    narrator = next(v for v in voices if v["name"] == "narrator")

    req = make_request("/api/v1/tts/synthesize", body={
        "text": "Hello world",
        "voice_id": narrator["voice_id"],
    })
    with patch("server.tts_engine.wav_to_format", return_value=b"audio-data"):
        resp = await server._handle_request(req)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_handle_synthesize_voice_not_found(server):
    req = make_request("/api/v1/tts/synthesize", body={
        "text": "hello", "voice_id": "nonexistent_id",
    })
    resp = await server._handle_request(req)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_handle_synthesize_missing_text(server):
    req = make_request("/api/v1/tts/synthesize", body={"voice_id": "x"})
    resp = await server._handle_request(req)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_handle_synthesize_missing_voice(server):
    req = make_request("/api/v1/tts/synthesize", body={"text": "hello"})
    resp = await server._handle_request(req)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_handle_synthesize_clone_mode(server):
    """Cloned voice uses reference audio path for synthesis."""
    profile = server.voice_manager.clone_voice_from_bytes(b"RIFF" + b"\x00" * 100, "TestClone")

    req = make_request("/api/v1/tts/synthesize", body={
        "text": "Hello",
        "voice_name": "TestClone",
    })
    with patch("server.tts_engine.wav_to_format", return_value=b"audio"):
        resp = await server._handle_request(req)
    assert resp.status_code == 200
    # Should have called generate_voice_clone (clone path)
    server.engine.generate_voice_clone.assert_called()


@pytest.mark.asyncio
async def test_handle_clone(server):
    audio_b64 = base64.b64encode(b"RIFF" + b"\x00" * 100).decode()
    req = make_request("/api/v1/tts/clone", body={
        "voice_name": "new_voice",
        "reference_audio": audio_b64,
    })
    resp = await server._handle_request(req)
    assert resp.status_code == 200
    data = json.loads(resp.body)
    assert data["name"] == "new_voice"
    assert data["type"] == "cloned"

    # Verify voice is now findable
    found = server.voice_manager.get_voice("new_voice")
    assert found is not None


@pytest.mark.asyncio
async def test_handle_clone_missing_fields(server):
    req = make_request("/api/v1/tts/clone", body={"voice_name": "x"})
    resp = await server._handle_request(req)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_handle_unknown_route(server):
    req = make_request("/api/v1/unknown", method="GET")
    resp = await server._handle_request(req)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_handle_synthesize_engine_not_loaded(server):
    server.engine.is_loaded = False
    req = make_request("/api/v1/tts/synthesize", body={
        "text": "hello", "voice_name": "Narrator",
    })
    resp = await server._handle_request(req)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_handle_delete_voice(server):
    # First create a voice to delete
    voices = server.voice_manager.list_voices()
    assert len(voices) > 0
    voice_id = voices[0]["voice_id"]

    req = make_request(f"/api/v1/tts/voices/{voice_id}", method="DELETE")
    resp = await server._handle_request(req)
    assert resp.status_code == 200 or resp.status_code is None  # None means 200 default
    body = json.loads(resp.body)
    assert body["deleted"] == voice_id


@pytest.mark.asyncio
async def test_handle_delete_voice_not_found(server):
    req = make_request("/api/v1/tts/voices/nonexistent-id", method="DELETE")
    resp = await server._handle_request(req)
    assert resp.status_code == 404
