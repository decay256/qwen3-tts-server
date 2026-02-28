"""Comprehensive tests for server/runpod_client.py.

Covers:
- health(): URL, headers, response passthrough
- runsync(): warm path (immediate COMPLETED)
- runsync(): cold path (IN_QUEUE → polling → COMPLETED)
- runsync(): /runsync timeout → fallback to /run + polling
- runsync(): total timeout expiry
- run_async(): job ID extraction
- poll_status(): status polling
- Error cases: network error, malformed JSON, auth errors, missing job ID
"""

import asyncio
import sys
import os

import pytest
import pytest_asyncio  # noqa: F401 — needed for async fixture support
from aioresponses import aioresponses
import aiohttp

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from server.runpod_client import RunPodClient


# ---------------------------------------------------------------------------
# Constants / fixtures
# ---------------------------------------------------------------------------

ENDPOINT_ID = "test-endpoint-abc123"
RUNPOD_API_KEY = "rp-secret-key"
TTS_API_KEY = "tts-api-key-xyz"
BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"


@pytest_asyncio.fixture
async def client():
    """Fresh RunPodClient for each test; closed after each test."""
    c = RunPodClient(
        endpoint_id=ENDPOINT_ID,
        runpod_api_key=RUNPOD_API_KEY,
        tts_api_key=TTS_API_KEY,
    )
    yield c
    await c.close()


# ---------------------------------------------------------------------------
# Helper: expected auth header value
# ---------------------------------------------------------------------------

AUTH_HEADER = f"Bearer {RUNPOD_API_KEY}"


# ---------------------------------------------------------------------------
# health()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_calls_correct_url(client):
    """health() must GET /health on the correct endpoint URL."""
    with aioresponses() as m:
        m.get(f"{BASE_URL}/health", payload={"workers": {"idle": 1}})
        result = await client.health()

    assert result == {"workers": {"idle": 1}}


@pytest.mark.asyncio
async def test_health_sends_auth_header(client):
    """health() must include Authorization header."""
    with aioresponses() as m:
        m.get(f"{BASE_URL}/health", payload={"workers": {}})
        await client.health()

    # aioresponses captures the call; verify via call_args
    call = m.requests[("GET", aiohttp.client.URL(f"{BASE_URL}/health"))][0]
    assert call.kwargs["headers"]["Authorization"] == AUTH_HEADER


@pytest.mark.asyncio
async def test_health_returns_raw_json(client):
    """health() should return whatever JSON the endpoint returns."""
    payload = {"status": "healthy", "gpu_count": 4}
    with aioresponses() as m:
        m.get(f"{BASE_URL}/health", payload=payload)
        result = await client.health()
    assert result == payload


@pytest.mark.asyncio
async def test_health_network_error_propagates(client):
    """Network errors during health() must propagate (not be swallowed)."""
    with aioresponses() as m:
        m.get(f"{BASE_URL}/health", exception=aiohttp.ClientConnectorError(
            connection_key=None, os_error=OSError("Connection refused")
        ))
        with pytest.raises(aiohttp.ClientError):
            await client.health()


# ---------------------------------------------------------------------------
# run_async()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_async_returns_job_id(client):
    """run_async() must POST to /run and return the job ID."""
    with aioresponses() as m:
        m.post(f"{BASE_URL}/run", payload={"id": "job-12345", "status": "IN_QUEUE"})
        job_id = await client.run_async("/api/v1/voices/design", {"text": "hi"})

    assert job_id == "job-12345"


@pytest.mark.asyncio
async def test_run_async_sends_correct_payload(client):
    """run_async() must embed endpoint, body, and api_key in the 'input' field."""
    endpoint = "/api/v1/voices/design"
    body = {"text": "hello", "instruct": "deep voice"}

    with aioresponses() as m:
        m.post(f"{BASE_URL}/run", payload={"id": "job-abc"})
        await client.run_async(endpoint, body)

    call = m.requests[("POST", aiohttp.client.URL(f"{BASE_URL}/run"))][0]
    sent = call.kwargs["json"]
    assert sent["input"]["endpoint"] == endpoint
    assert sent["input"]["body"] == body
    assert sent["input"]["api_key"] == TTS_API_KEY


@pytest.mark.asyncio
async def test_run_async_missing_id_returns_empty_string(client):
    """run_async() returns '' when the response has no 'id' field."""
    with aioresponses() as m:
        m.post(f"{BASE_URL}/run", payload={"status": "IN_QUEUE"})
        job_id = await client.run_async("/api/v1/status")
    assert job_id == ""


@pytest.mark.asyncio
async def test_run_async_sends_auth_header(client):
    """run_async() must include Authorization header."""
    with aioresponses() as m:
        m.post(f"{BASE_URL}/run", payload={"id": "job-x"})
        await client.run_async("/api/v1/status")

    call = m.requests[("POST", aiohttp.client.URL(f"{BASE_URL}/run"))][0]
    assert call.kwargs["headers"]["Authorization"] == AUTH_HEADER


@pytest.mark.asyncio
async def test_run_async_uses_empty_body_when_none(client):
    """run_async() defaults body to {} when None is passed."""
    with aioresponses() as m:
        m.post(f"{BASE_URL}/run", payload={"id": "job-y"})
        await client.run_async("/api/v1/status", None)

    call = m.requests[("POST", aiohttp.client.URL(f"{BASE_URL}/run"))][0]
    assert call.kwargs["json"]["input"]["body"] == {}


# ---------------------------------------------------------------------------
# poll_status()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_status_returns_status_dict(client):
    """poll_status() must GET /status/{job_id} and return the JSON."""
    job_id = "job-poll-001"
    with aioresponses() as m:
        m.get(f"{BASE_URL}/status/{job_id}", payload={"id": job_id, "status": "IN_PROGRESS"})
        result = await client.poll_status(job_id)

    assert result == {"id": job_id, "status": "IN_PROGRESS"}


@pytest.mark.asyncio
async def test_poll_status_sends_auth_header(client):
    """poll_status() must include Authorization header."""
    job_id = "job-auth-check"
    with aioresponses() as m:
        m.get(f"{BASE_URL}/status/{job_id}", payload={"status": "COMPLETED"})
        await client.poll_status(job_id)

    call = m.requests[("GET", aiohttp.client.URL(f"{BASE_URL}/status/{job_id}"))][0]
    assert call.kwargs["headers"]["Authorization"] == AUTH_HEADER


@pytest.mark.asyncio
async def test_poll_status_completed(client):
    """poll_status() works for COMPLETED status."""
    job_id = "job-done"
    payload = {"id": job_id, "status": "COMPLETED", "output": {"audio": "base64data"}}
    with aioresponses() as m:
        m.get(f"{BASE_URL}/status/{job_id}", payload=payload)
        result = await client.poll_status(job_id)
    assert result["status"] == "COMPLETED"
    assert result["output"]["audio"] == "base64data"


@pytest.mark.asyncio
async def test_poll_status_network_error_propagates(client):
    """Network errors in poll_status() must propagate."""
    job_id = "job-err"
    with aioresponses() as m:
        m.get(f"{BASE_URL}/status/{job_id}", exception=aiohttp.ServerDisconnectedError())
        with pytest.raises(aiohttp.ServerDisconnectedError):
            await client.poll_status(job_id)


# ---------------------------------------------------------------------------
# runsync() — warm path (immediate COMPLETED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runsync_warm_path_completed_immediately(client, monkeypatch):
    """runsync() returns immediately when /runsync returns COMPLETED."""
    # Patch sleep so the test doesn't wait
    monkeypatch.setattr(asyncio, "sleep", lambda _: asyncio.coroutine(lambda: None)())

    endpoint = "/api/v1/voices/design"
    body = {"text": "hello", "instruct": "warm voice"}
    expected = {"id": "job-warm", "status": "COMPLETED", "output": {"audio": "abc"}}

    with aioresponses() as m:
        m.post(f"{BASE_URL}/runsync", payload=expected)
        result = await client.runsync(endpoint, body)

    assert result["status"] == "COMPLETED"
    assert result["output"]["audio"] == "abc"


@pytest.mark.asyncio
async def test_runsync_warm_failed_returned_immediately(client, monkeypatch):
    """runsync() returns FAILED immediately without polling when runsync reports FAILED."""
    monkeypatch.setattr(asyncio, "sleep", lambda _: asyncio.coroutine(lambda: None)())

    expected = {"id": "job-fail", "status": "FAILED", "error": "OOM"}

    with aioresponses() as m:
        m.post(f"{BASE_URL}/runsync", payload=expected)
        result = await client.runsync("/api/v1/status")

    assert result["status"] == "FAILED"
    assert result["error"] == "OOM"


@pytest.mark.asyncio
async def test_runsync_sends_correct_payload(client, monkeypatch):
    """runsync() must embed endpoint, body, and api_key in payload."""
    monkeypatch.setattr(asyncio, "sleep", lambda _: asyncio.coroutine(lambda: None)())

    endpoint = "/api/v1/tts/synthesize"
    body = {"text": "test", "ref_audio": "base64ref"}

    with aioresponses() as m:
        m.post(f"{BASE_URL}/runsync", payload={"status": "COMPLETED", "output": {}})
        await client.runsync(endpoint, body)

    call = m.requests[("POST", aiohttp.client.URL(f"{BASE_URL}/runsync"))][0]
    sent = call.kwargs["json"]
    assert sent["input"]["endpoint"] == endpoint
    assert sent["input"]["body"] == body
    assert sent["input"]["api_key"] == TTS_API_KEY


@pytest.mark.asyncio
async def test_runsync_sends_auth_header(client, monkeypatch):
    """runsync() must include Authorization header on /runsync call."""
    monkeypatch.setattr(asyncio, "sleep", lambda _: asyncio.coroutine(lambda: None)())

    with aioresponses() as m:
        m.post(f"{BASE_URL}/runsync", payload={"status": "COMPLETED", "output": {}})
        await client.runsync("/api/v1/status")

    call = m.requests[("POST", aiohttp.client.URL(f"{BASE_URL}/runsync"))][0]
    assert call.kwargs["headers"]["Authorization"] == AUTH_HEADER


# ---------------------------------------------------------------------------
# runsync() — cold path (IN_QUEUE → polling → COMPLETED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runsync_cold_path_polls_until_completed(client, monkeypatch):
    """When /runsync returns IN_QUEUE, runsync() must poll until COMPLETED."""
    sleep_calls = []

    async def fast_sleep(secs):
        sleep_calls.append(secs)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    job_id = "job-cold-001"
    runsync_response = {"id": job_id, "status": "IN_QUEUE"}
    poll_queued = {"id": job_id, "status": "IN_QUEUE"}
    poll_progress = {"id": job_id, "status": "IN_PROGRESS"}
    poll_done = {"id": job_id, "status": "COMPLETED", "output": {"audio": "xyz"}}

    with aioresponses() as m:
        m.post(f"{BASE_URL}/runsync", payload=runsync_response)
        m.get(f"{BASE_URL}/status/{job_id}", payload=poll_queued)
        m.get(f"{BASE_URL}/status/{job_id}", payload=poll_progress)
        m.get(f"{BASE_URL}/status/{job_id}", payload=poll_done)

        result = await client.runsync("/api/v1/voices/design", {}, timeout=120)

    assert result["status"] == "COMPLETED"
    assert result["output"]["audio"] == "xyz"
    assert len(sleep_calls) == 3, "Should have slept 3 times before completing"


@pytest.mark.asyncio
async def test_runsync_cold_path_in_progress_then_completed(client, monkeypatch):
    """Cold path: /runsync returns IN_PROGRESS → polling reaches COMPLETED."""
    async def fast_sleep(_): pass
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    job_id = "job-inprog"
    with aioresponses() as m:
        m.post(f"{BASE_URL}/runsync", payload={"id": job_id, "status": "IN_PROGRESS"})
        m.get(f"{BASE_URL}/status/{job_id}", payload={"status": "IN_PROGRESS"})
        m.get(f"{BASE_URL}/status/{job_id}", payload={"status": "COMPLETED", "output": {}})
        result = await client.runsync("/api/v1/status", timeout=120)

    assert result["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_runsync_cold_path_uses_job_id_from_runsync_response(client, monkeypatch):
    """Cold path: job ID comes from /runsync response, used for polling."""
    async def fast_sleep(_): pass
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    job_id = "job-id-tracking"
    with aioresponses() as m:
        m.post(f"{BASE_URL}/runsync", payload={"id": job_id, "status": "IN_QUEUE"})
        m.get(f"{BASE_URL}/status/{job_id}", payload={"status": "COMPLETED", "output": {}})
        await client.runsync("/api/v1/status", timeout=120)

    # Verify the correct status URL was polled
    status_url = aiohttp.client.URL(f"{BASE_URL}/status/{job_id}")
    assert status_url in [aiohttp.client.URL(str(k[1])) for k in m.requests]


# ---------------------------------------------------------------------------
# runsync() — /runsync timeout → fallback to /run + polling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runsync_timeout_falls_back_to_run_and_poll(client, monkeypatch):
    """/runsync asyncio.TimeoutError triggers fallback to /run + polling."""
    async def fast_sleep(_): pass
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    job_id = "job-fallback"
    with aioresponses() as m:
        # /runsync times out
        m.post(f"{BASE_URL}/runsync", exception=asyncio.TimeoutError())
        # Fallback: submit async job
        m.post(f"{BASE_URL}/run", payload={"id": job_id})
        # Poll returns complete
        m.get(f"{BASE_URL}/status/{job_id}", payload={"status": "COMPLETED", "output": {"data": "ok"}})

        result = await client.runsync("/api/v1/voices/design", {"text": "hi"}, timeout=120)

    assert result["status"] == "COMPLETED"
    assert result["output"]["data"] == "ok"

    # Verify both /run and /status were called
    run_url = aiohttp.client.URL(f"{BASE_URL}/run")
    status_url = aiohttp.client.URL(f"{BASE_URL}/status/{job_id}")
    assert run_url in [aiohttp.client.URL(str(k[1])) for k in m.requests]
    assert status_url in [aiohttp.client.URL(str(k[1])) for k in m.requests]


@pytest.mark.asyncio
async def test_runsync_fallback_job_polls_multiple_times(client, monkeypatch):
    """After fallback to /run, polling continues until COMPLETED."""
    sleep_calls = []

    async def fast_sleep(secs):
        sleep_calls.append(secs)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    job_id = "job-multi-poll"
    with aioresponses() as m:
        m.post(f"{BASE_URL}/runsync", exception=asyncio.TimeoutError())
        m.post(f"{BASE_URL}/run", payload={"id": job_id})
        m.get(f"{BASE_URL}/status/{job_id}", payload={"status": "IN_QUEUE"})
        m.get(f"{BASE_URL}/status/{job_id}", payload={"status": "IN_PROGRESS"})
        m.get(f"{BASE_URL}/status/{job_id}", payload={"status": "COMPLETED", "output": {}})

        result = await client.runsync("/api/v1/status", timeout=120)

    assert result["status"] == "COMPLETED"
    assert len(sleep_calls) == 3


@pytest.mark.asyncio
async def test_runsync_fallback_no_job_id_returns_failed(client, monkeypatch):
    """If /run returns no job ID, runsync() returns a FAILED result."""
    async def fast_sleep(_): pass
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    with aioresponses() as m:
        m.post(f"{BASE_URL}/runsync", exception=asyncio.TimeoutError())
        # /run response has no 'id'
        m.post(f"{BASE_URL}/run", payload={"status": "ERROR"})

        result = await client.runsync("/api/v1/voices/design", timeout=120)

    assert result["status"] == "FAILED"
    assert "No job ID" in result["error"]


# ---------------------------------------------------------------------------
# runsync() — total timeout expiry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runsync_total_timeout_returns_failed(client, monkeypatch):
    """When deadline passes before completion, runsync() returns FAILED with timeout message."""
    import time

    # Simulate time advancing past deadline on first poll
    real_time = time.time
    call_count = 0

    def fake_time():
        nonlocal call_count
        call_count += 1
        # After first call (initial deadline setup), return time past deadline
        if call_count > 1:
            return real_time() + 10000
        return real_time()

    async def fast_sleep(_): pass
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr("server.runpod_client.time", type("t", (), {"time": staticmethod(fake_time)})())

    job_id = "job-timeout"
    with aioresponses() as m:
        m.post(f"{BASE_URL}/runsync", payload={"id": job_id, "status": "IN_QUEUE"})
        # Status calls shouldn't happen because deadline already passed
        # but add one just in case
        m.get(f"{BASE_URL}/status/{job_id}", payload={"status": "IN_QUEUE"})

        result = await client.runsync("/api/v1/voices/design", timeout=1)

    assert result["status"] == "FAILED"
    assert "timed out" in result["error"]
    assert job_id in result["error"]


@pytest.mark.asyncio
async def test_runsync_timeout_message_includes_job_id(client, monkeypatch):
    """Timeout error message must include the job ID for debugging."""
    import time

    original_time = time.time
    first_call = True

    def fake_time():
        nonlocal first_call
        if first_call:
            first_call = False
            return original_time()
        return original_time() + 99999

    async def fast_sleep(_): pass
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr("server.runpod_client.time", type("t", (), {"time": staticmethod(fake_time)})())

    job_id = "job-id-in-error"
    with aioresponses() as m:
        m.post(f"{BASE_URL}/runsync", payload={"id": job_id, "status": "IN_QUEUE"})
        m.get(f"{BASE_URL}/status/{job_id}", payload={"status": "IN_QUEUE"})

        result = await client.runsync("/api/v1/status", timeout=1)

    assert result["status"] == "FAILED"
    assert job_id in result["error"]


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_raises_on_non_json_response(client):
    """health() should propagate JSON decode errors from malformed responses."""
    with aioresponses() as m:
        m.get(f"{BASE_URL}/health", body=b"not-json", content_type="text/plain")
        with pytest.raises(Exception):
            await client.health()


@pytest.mark.asyncio
async def test_runsync_network_error_on_runsync_propagates(client, monkeypatch):
    """Non-timeout ClientErrors on /runsync must propagate (not be caught)."""
    async def fast_sleep(_): pass
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    with aioresponses() as m:
        m.post(f"{BASE_URL}/runsync", exception=aiohttp.ServerDisconnectedError())
        with pytest.raises(aiohttp.ServerDisconnectedError):
            await client.runsync("/api/v1/status")


@pytest.mark.asyncio
async def test_run_async_network_error_propagates(client):
    """Network errors in run_async() must propagate."""
    with aioresponses() as m:
        m.post(f"{BASE_URL}/run", exception=aiohttp.ClientError("connection failed"))
        with pytest.raises(aiohttp.ClientError):
            await client.run_async("/api/v1/status")


@pytest.mark.asyncio
async def test_poll_status_failed_job(client):
    """poll_status() returns FAILED response unchanged."""
    job_id = "job-failed"
    payload = {"id": job_id, "status": "FAILED", "error": "CUDA OOM"}
    with aioresponses() as m:
        m.get(f"{BASE_URL}/status/{job_id}", payload=payload)
        result = await client.poll_status(job_id)
    assert result["status"] == "FAILED"
    assert result["error"] == "CUDA OOM"


@pytest.mark.asyncio
async def test_runsync_uses_none_body_as_empty_dict(client, monkeypatch):
    """runsync() defaults body to {} when None is passed."""
    async def fast_sleep(_): pass
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    with aioresponses() as m:
        m.post(f"{BASE_URL}/runsync", payload={"status": "COMPLETED", "output": {}})
        await client.runsync("/api/v1/status", None)

    call = m.requests[("POST", aiohttp.client.URL(f"{BASE_URL}/runsync"))][0]
    assert call.kwargs["json"]["input"]["body"] == {}


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_reuses_session(client):
    """Client reuses the same aiohttp session across calls."""
    with aioresponses() as m:
        m.get(f"{BASE_URL}/health", payload={"ok": True})
        m.get(f"{BASE_URL}/health", payload={"ok": True})
        session1 = await client._get_session()
        session2 = await client._get_session()
        assert session1 is session2


@pytest.mark.asyncio
async def test_close_closes_session(client):
    """close() closes the underlying aiohttp session."""
    with aioresponses() as m:
        m.get(f"{BASE_URL}/health", payload={})
        await client.health()  # Force session creation

    assert client._session is not None
    await client.close()
    assert client._session.closed


@pytest.mark.asyncio
async def test_close_is_idempotent(client):
    """Calling close() multiple times must not raise."""
    await client.close()
    await client.close()


@pytest.mark.asyncio
async def test_session_recreated_after_close(client):
    """After close(), the next request creates a new session."""
    with aioresponses() as m:
        m.get(f"{BASE_URL}/health", payload={})
        await client.health()

    await client.close()

    with aioresponses() as m:
        m.get(f"{BASE_URL}/health", payload={"after_close": True})
        result = await client.health()

    assert result == {"after_close": True}
