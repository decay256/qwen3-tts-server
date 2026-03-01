"""Tests for POST /api/v1/tts/warmup relay endpoint.

Covers:
- Returns 401 when auth is missing
- Returns {"status": "connected"} when tunnel is already up
- Returns 503 when RunPod is not configured
- Returns {"status": "warming"} and fires run_async when RunPod is configured
- Returns 502 when run_async raises an exception
"""

import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from server.remote_relay import RemoteRelay


# ---------------------------------------------------------------------------
# Minimal relay fixture
# ---------------------------------------------------------------------------

API_KEY = "test-relay-key"

BASE_CONFIG = {
    "api_key": API_KEY,
    "remote": {"bind": "127.0.0.1", "port": 19800},
}

AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def make_relay(tunnel_has_client: bool = False, with_runpod: bool = False) -> RemoteRelay:
    """Build a RemoteRelay with controllable tunnel and RunPod state."""
    relay = RemoteRelay.__new__(RemoteRelay)
    relay.config = BASE_CONFIG
    relay.api_key = API_KEY
    from server.auth import AuthManager
    relay.auth_manager = AuthManager(API_KEY)
    relay.start_time = 0.0

    # Tunnel stub
    tunnel = MagicMock()
    tunnel.has_client = tunnel_has_client
    tunnel.connected_clients = 1 if tunnel_has_client else 0
    relay.tunnel_server = tunnel

    # RunPod stub
    if with_runpod:
        runpod = MagicMock()
        runpod.run_async = AsyncMock(return_value="job-warm-001")
        relay.runpod = runpod
    else:
        relay.runpod = None

    return relay


@pytest_asyncio.fixture
async def client_no_backend():
    """TestClient with no tunnel and no RunPod."""
    relay = make_relay(tunnel_has_client=False, with_runpod=False)
    app = relay.create_app()
    async with TestClient(TestServer(app)) as client:
        yield client


@pytest_asyncio.fixture
async def client_tunnel_connected():
    """TestClient with an active tunnel connection."""
    relay = make_relay(tunnel_has_client=True, with_runpod=False)
    app = relay.create_app()
    async with TestClient(TestServer(app)) as client:
        yield client


@pytest_asyncio.fixture
async def client_with_runpod():
    """TestClient with RunPod configured (no tunnel)."""
    relay = make_relay(tunnel_has_client=False, with_runpod=True)
    app = relay.create_app()
    async with TestClient(TestServer(app)) as client:
        # Attach relay reference so tests can inspect the RunPod mock
        client._relay = relay  # type: ignore[attr-defined]
        yield client


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warmup_requires_auth(client_no_backend):
    """POST /api/v1/tts/warmup without auth must return 401."""
    resp = await client_no_backend.post("/api/v1/tts/warmup")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_warmup_wrong_key_returns_401(client_no_backend):
    """Wrong API key returns 401."""
    resp = await client_no_backend.post(
        "/api/v1/tts/warmup",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status == 401


# ---------------------------------------------------------------------------
# Already connected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warmup_tunnel_connected_returns_connected(client_tunnel_connected):
    """When tunnel is connected, warmup returns {"status": "connected"}."""
    resp = await client_tunnel_connected.post(
        "/api/v1/tts/warmup",
        headers=AUTH_HEADERS,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "connected"
    assert "already connected" in data["message"].lower()


# ---------------------------------------------------------------------------
# No RunPod
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warmup_no_runpod_returns_503(client_no_backend):
    """When RunPod is not configured, warmup must return 503."""
    resp = await client_no_backend.post(
        "/api/v1/tts/warmup",
        headers=AUTH_HEADERS,
    )
    assert resp.status == 503
    data = await resp.json()
    assert "error" in data
    assert "runpod" in data["error"].lower()


# ---------------------------------------------------------------------------
# RunPod configured — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warmup_runpod_submits_job(client_with_runpod):
    """warmup() submits a job to RunPod and returns {"status": "warming"}."""
    resp = await client_with_runpod.post(
        "/api/v1/tts/warmup",
        headers=AUTH_HEADERS,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "warming"
    assert "runpod" in data["message"].lower() or "worker" in data["message"].lower()

    # Verify run_async was called
    client_with_runpod._relay.runpod.run_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_warmup_runpod_calls_status_endpoint(client_with_runpod):
    """warmup() must submit a job targeting /api/v1/status (cheap, no GPU work)."""
    resp = await client_with_runpod.post(
        "/api/v1/tts/warmup",
        headers=AUTH_HEADERS,
    )
    assert resp.status == 200

    relay = client_with_runpod._relay
    call_args = relay.runpod.run_async.call_args
    # First positional arg is the endpoint
    endpoint_called = call_args[0][0] if call_args[0] else call_args.kwargs.get("endpoint")
    assert endpoint_called == "/api/v1/status"


@pytest.mark.asyncio
async def test_warmup_does_not_poll_for_job_completion(client_with_runpod):
    """warmup() is fire-and-forget: it MUST NOT call poll_status after submitting.

    run_async() is correctly awaited (to get the job ID / surface submission
    errors), but we must never poll for job completion.
    """
    relay = client_with_runpod._relay
    # Attach a spy to poll_status so we can assert it was never called
    relay.runpod.poll_status = AsyncMock(return_value={"status": "COMPLETED", "output": {}})

    resp = await client_with_runpod.post(
        "/api/v1/tts/warmup",
        headers=AUTH_HEADERS,
    )
    assert resp.status == 200

    # poll_status must NOT have been called — warmup is fire-and-forget
    relay.runpod.poll_status.assert_not_awaited()


# ---------------------------------------------------------------------------
# RunPod configured — error from run_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warmup_runpod_run_async_error_returns_502(client_with_runpod):
    """When run_async() raises, warmup returns 502 with error detail."""
    client_with_runpod._relay.runpod.run_async = AsyncMock(
        side_effect=Exception("Connection refused")
    )

    resp = await client_with_runpod.post(
        "/api/v1/tts/warmup",
        headers=AUTH_HEADERS,
    )
    assert resp.status == 502
    data = await resp.json()
    assert "error" in data


# ---------------------------------------------------------------------------
# Idempotency: noop when workers already ready (Sprint 3 — issue #22)
# ---------------------------------------------------------------------------

def make_relay_with_health(
    tunnel_has_client: bool = False,
    health_response: dict | None = None,
) -> RemoteRelay:
    """Build a RemoteRelay with a properly mocked RunPod health() call."""
    relay = RemoteRelay.__new__(RemoteRelay)
    relay.config = BASE_CONFIG
    relay.api_key = API_KEY
    from server.auth import AuthManager
    relay.auth_manager = AuthManager(API_KEY)
    relay.start_time = 0.0

    tunnel = MagicMock()
    tunnel.has_client = tunnel_has_client
    tunnel.connected_clients = 1 if tunnel_has_client else 0
    relay.tunnel_server = tunnel

    runpod = MagicMock()
    runpod.run_async = AsyncMock(return_value="job-warm-002")
    runpod.health = AsyncMock(return_value=health_response or {})
    relay.runpod = runpod

    return relay


@pytest_asyncio.fixture
async def client_runpod_workers_idle():
    """RunPod configured, 2 idle workers — warmup should noop."""
    health = {
        "workers": {"ready": 1, "idle": 1, "initializing": 0, "running": 0, "throttled": 0, "unhealthy": 0},
        "jobs": {"queued": 0, "inProgress": 0, "completed": 5, "failed": 0, "retried": 0, "badfailed": 0},
    }
    relay = make_relay_with_health(health_response=health)
    app = relay.create_app()
    async with TestClient(TestServer(app)) as client:
        client._relay = relay  # type: ignore[attr-defined]
        yield client


@pytest_asyncio.fixture
async def client_runpod_workers_busy():
    """RunPod configured, all workers running (none idle/ready) — warmup should submit a job."""
    health = {
        "workers": {"ready": 0, "idle": 0, "initializing": 0, "running": 2, "throttled": 0, "unhealthy": 0},
        "jobs": {"queued": 1, "inProgress": 2, "completed": 10, "failed": 0, "retried": 0, "badfailed": 0},
    }
    relay = make_relay_with_health(health_response=health)
    app = relay.create_app()
    async with TestClient(TestServer(app)) as client:
        client._relay = relay  # type: ignore[attr-defined]
        yield client


@pytest.mark.asyncio
async def test_warmup_noop_when_workers_ready(client_runpod_workers_idle):
    """Warmup returns noop when workers are already idle/ready — no job submitted."""
    resp = await client_runpod_workers_idle.post(
        "/api/v1/tts/warmup",
        headers=AUTH_HEADERS,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "noop"
    assert "already ready" in data["message"].lower() or "no warmup" in data["message"].lower()
    assert data["workers_ready"] == 2  # 1 ready + 1 idle

    # Must NOT have submitted a new job
    client_runpod_workers_idle._relay.runpod.run_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_warmup_submits_job_when_workers_busy(client_runpod_workers_busy):
    """Warmup submits a job when all workers are running (none idle/ready)."""
    resp = await client_runpod_workers_busy.post(
        "/api/v1/tts/warmup",
        headers=AUTH_HEADERS,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "warming"

    # Must have submitted a new job
    client_runpod_workers_busy._relay.runpod.run_async.assert_awaited_once()
