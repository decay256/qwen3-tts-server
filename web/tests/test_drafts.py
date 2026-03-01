"""Tests for draft management routes.

NOTE: TTS relay calls in background tasks are NOT tested here — they hit an
external GPU backend. These tests verify the CRUD layer and status transitions
without triggering actual audio generation.
"""

import base64
import io
import struct
import wave
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


# ── Fixtures ──────────────────────────────────────────────────────────────────

async def _create_character(client: AsyncClient, auth_headers: dict) -> str:
    resp = await client.post("/api/v1/characters", json={
        "name": "Kira",
        "base_description": "Husky woman",
    }, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()["id"]


DRAFT_PAYLOAD = {
    "preset_name": "angry",
    "preset_type": "emotion",
    "intensity": "medium",
    "text": "Hello, I am furious about this!",
    "instruct": "Speak with controlled anger, sharp consonants",
    "language": "English",
}


def _make_fake_audio_b64() -> str:
    """Generate a minimal valid WAV file and return as base64."""
    sample_rate = 22050
    num_samples = sample_rate
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{num_samples}h", *([0] * num_samples)))
    return base64.b64encode(buf.getvalue()).decode()


# ── POST /api/v1/drafts ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_draft_no_character(client: AsyncClient, auth_headers: dict):
    """Draft created without character_id."""
    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        resp = await client.post("/api/v1/drafts", json=DRAFT_PAYLOAD, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()["draft"]
    assert data["status"] == "pending"
    assert data["preset_name"] == "angry"
    assert data["preset_type"] == "emotion"
    assert data["intensity"] == "medium"
    assert "audio_b64" not in data  # summary must not include audio


@pytest.mark.asyncio
async def test_create_draft_with_character(client: AsyncClient, auth_headers: dict):
    char_id = await _create_character(client, auth_headers)
    payload = {**DRAFT_PAYLOAD, "character_id": char_id}
    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        resp = await client.post("/api/v1/drafts", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()["draft"]
    assert data["character_id"] == char_id


@pytest.mark.asyncio
async def test_create_draft_invalid_character(client: AsyncClient, auth_headers: dict):
    payload = {**DRAFT_PAYLOAD, "character_id": "nonexistent-id"}
    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        resp = await client.post("/api/v1/drafts", json=payload, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_draft_missing_intensity_for_emotion(client: AsyncClient, auth_headers: dict):
    payload = {k: v for k, v in DRAFT_PAYLOAD.items() if k != "intensity"}
    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        resp = await client.post("/api/v1/drafts", json=payload, headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_draft_invalid_preset_type(client: AsyncClient, auth_headers: dict):
    payload = {**DRAFT_PAYLOAD, "preset_type": "unknown"}
    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        resp = await client.post("/api/v1/drafts", json=payload, headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_draft_mode_no_intensity_required(client: AsyncClient, auth_headers: dict):
    """Mode presets don't require intensity."""
    payload = {
        "preset_name": "whisper",
        "preset_type": "mode",
        "text": "This is a whispered secret.",
        "instruct": "Speak in a low whisper",
    }
    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        resp = await client.post("/api/v1/drafts", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["draft"]["intensity"] is None


# ── GET /api/v1/drafts ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_drafts_empty(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/drafts", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["drafts"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_drafts(client: AsyncClient, auth_headers: dict):
    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        await client.post("/api/v1/drafts", json=DRAFT_PAYLOAD, headers=auth_headers)
        await client.post("/api/v1/drafts", json=DRAFT_PAYLOAD, headers=auth_headers)

    resp = await client.get("/api/v1/drafts", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["drafts"]) == 2
    # Verify audio_b64 not in list response
    for draft in data["drafts"]:
        assert "audio_b64" not in draft


@pytest.mark.asyncio
async def test_list_drafts_status_filter(client: AsyncClient, auth_headers: dict):
    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        await client.post("/api/v1/drafts", json=DRAFT_PAYLOAD, headers=auth_headers)

    resp = await client.get("/api/v1/drafts?status=pending", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    resp = await client.get("/api/v1/drafts?status=ready", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_drafts_invalid_status_filter(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/drafts?status=banana", headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_drafts_character_filter(client: AsyncClient, auth_headers: dict):
    char_id = await _create_character(client, auth_headers)
    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        await client.post("/api/v1/drafts", json={**DRAFT_PAYLOAD, "character_id": char_id}, headers=auth_headers)
        await client.post("/api/v1/drafts", json=DRAFT_PAYLOAD, headers=auth_headers)

    resp = await client.get(f"/api/v1/drafts?character_id={char_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# ── GET /api/v1/drafts/{draft_id} ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_draft_includes_audio_field(client: AsyncClient, auth_headers: dict):
    """Full draft response should include audio_b64 key (even if None for pending)."""
    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        create_resp = await client.post("/api/v1/drafts", json=DRAFT_PAYLOAD, headers=auth_headers)
    draft_id = create_resp.json()["draft"]["id"]

    resp = await client.get(f"/api/v1/drafts/{draft_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["draft"]
    assert "audio_b64" in data  # key must be present in detail view
    assert data["id"] == draft_id


@pytest.mark.asyncio
async def test_get_draft_not_found(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/drafts/nonexistent-id", headers=auth_headers)
    assert resp.status_code == 404


# ── DELETE /api/v1/drafts/{draft_id} ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_draft(client: AsyncClient, auth_headers: dict):
    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        create_resp = await client.post("/api/v1/drafts", json=DRAFT_PAYLOAD, headers=auth_headers)
    draft_id = create_resp.json()["draft"]["id"]

    resp = await client.delete(f"/api/v1/drafts/{draft_id}", headers=auth_headers)
    assert resp.status_code == 204

    get_resp = await client.get(f"/api/v1/drafts/{draft_id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_draft_not_found(client: AsyncClient, auth_headers: dict):
    resp = await client.delete("/api/v1/drafts/nonexistent-id", headers=auth_headers)
    assert resp.status_code == 404


# ── POST /api/v1/drafts/{draft_id}/approve ───────────────────────────────────

@pytest.mark.asyncio
async def test_approve_pending_draft_fails(client: AsyncClient, auth_headers: dict):
    """Cannot approve a pending draft."""
    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        create_resp = await client.post("/api/v1/drafts", json=DRAFT_PAYLOAD, headers=auth_headers)
    draft_id = create_resp.json()["draft"]["id"]
    char_id = await _create_character(client, auth_headers)

    resp = await client.post(
        f"/api/v1/drafts/{draft_id}/approve",
        json={"character_id": char_id},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "ready" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_approve_ready_draft_creates_template(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Approving a ready draft creates a Template and sets draft.status=approved."""
    from web.app.models.draft import Draft, DRAFT_STATUS_READY

    fake_audio_b64 = _make_fake_audio_b64()
    char_id = await _create_character(client, auth_headers)

    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        create_resp = await client.post(
            "/api/v1/drafts",
            json={**DRAFT_PAYLOAD, "character_id": char_id},
            headers=auth_headers,
        )
    draft_id = create_resp.json()["draft"]["id"]

    # Set draft to ready with fake audio via test session
    result = await db_session.execute(select(Draft).where(Draft.id == draft_id))
    draft = result.scalar_one()
    draft.status = DRAFT_STATUS_READY
    draft.audio_b64 = fake_audio_b64
    draft.duration_s = 1.0
    await db_session.commit()

    # Approve
    resp = await client.post(
        f"/api/v1/drafts/{draft_id}/approve",
        json={"character_id": char_id, "name": "Kira Angry Medium"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    tmpl = resp.json()["template"]
    assert tmpl["name"] == "Kira Angry Medium"
    assert tmpl["character_id"] == char_id
    assert tmpl["draft_id"] == draft_id
    assert "audio_b64" not in tmpl  # summary returned from approve

    # Verify draft is now approved
    draft_resp = await client.get(f"/api/v1/drafts/{draft_id}", headers=auth_headers)
    assert draft_resp.json()["draft"]["status"] == "approved"


# ── POST /api/v1/drafts/{draft_id}/regenerate ────────────────────────────────

@pytest.mark.asyncio
async def test_regenerate_draft(client: AsyncClient, auth_headers: dict):
    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        create_resp = await client.post("/api/v1/drafts", json=DRAFT_PAYLOAD, headers=auth_headers)
    draft_id = create_resp.json()["draft"]["id"]

    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        resp = await client.post(
            f"/api/v1/drafts/{draft_id}/regenerate",
            json={"instruct": "Speak with extreme rage"},
            headers=auth_headers,
        )
    assert resp.status_code == 201
    new_draft = resp.json()["draft"]
    assert new_draft["id"] != draft_id  # new draft
    assert new_draft["status"] == "pending"
    assert new_draft["instruct"] == "Speak with extreme rage"

    # Original still exists
    orig_resp = await client.get(f"/api/v1/drafts/{draft_id}", headers=auth_headers)
    assert orig_resp.status_code == 200


# ── Isolation ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_drafts_isolated_per_user(client: AsyncClient, auth_headers: dict):
    """User A cannot see User B's drafts."""
    await client.post("/auth/register", json={"email": "b@b.com", "password": "password123"})
    login_resp = await client.post("/auth/login", json={"email": "b@b.com", "password": "password123"})
    headers_b = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        await client.post("/api/v1/drafts", json=DRAFT_PAYLOAD, headers=auth_headers)  # user A
        await client.post("/api/v1/drafts", json=DRAFT_PAYLOAD, headers=headers_b)     # user B

    resp_a = await client.get("/api/v1/drafts", headers=auth_headers)
    resp_b = await client.get("/api/v1/drafts", headers=headers_b)

    assert resp_a.json()["total"] == 1
    assert resp_b.json()["total"] == 1
