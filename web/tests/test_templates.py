"""Tests for template management routes."""

import base64
import io
import struct
import wave
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _make_fake_audio_b64() -> str:
    """Generate a minimal valid WAV file and return as base64."""
    sample_rate = 22050
    num_samples = sample_rate  # 1 second
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{num_samples}h", *([0] * num_samples)))
    return base64.b64encode(buf.getvalue()).decode()


async def _create_character(client: AsyncClient, auth_headers: dict, name: str = "Kira") -> str:
    resp = await client.post("/api/v1/characters", json={
        "name": name,
        "base_description": "Test voice",
    }, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()["id"]


async def _create_ready_draft(
    client: AsyncClient,
    auth_headers: dict,
    char_id: str,
    db_session: AsyncSession,
    preset_type: str = "emotion",
) -> str:
    """Create a draft and manually set it to ready with fake audio."""
    from web.app.models.draft import Draft, DRAFT_STATUS_READY

    if preset_type == "emotion":
        payload = {
            "preset_name": "calm",
            "preset_type": "emotion",
            "intensity": "medium",
            "text": "Hello there, I am perfectly calm.",
            "instruct": "Speak with a serene, calm voice",
            "character_id": char_id,
        }
    else:
        payload = {
            "preset_name": "whisper",
            "preset_type": "mode",
            "text": "Whispering now softly.",
            "instruct": "Speak in a low whisper",
        }

    with patch("web.app.routes.drafts._generate_draft_audio", new_callable=AsyncMock):
        resp = await client.post("/api/v1/drafts", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    draft_id = resp.json()["draft"]["id"]

    # Set to ready with fake audio using test session
    fake_audio = _make_fake_audio_b64()
    result = await db_session.execute(select(Draft).where(Draft.id == draft_id))
    draft = result.scalar_one()
    draft.status = DRAFT_STATUS_READY
    draft.audio_b64 = fake_audio
    draft.duration_s = 1.0
    await db_session.commit()

    return draft_id


async def _approve_draft(
    client: AsyncClient,
    auth_headers: dict,
    draft_id: str,
    char_id: str,
    name: str = "Test Template",
) -> str:
    resp = await client.post(
        f"/api/v1/drafts/{draft_id}/approve",
        json={"character_id": char_id, "name": name},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["template"]["id"]


# ── GET /api/v1/templates ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_templates_empty(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/templates", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["templates"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_templates(client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
    char_id = await _create_character(client, auth_headers)
    draft_id = await _create_ready_draft(client, auth_headers, char_id, db_session)
    await _approve_draft(client, auth_headers, draft_id, char_id, "Template 1")

    resp = await client.get("/api/v1/templates", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    tmpl = data["templates"][0]
    assert tmpl["name"] == "Template 1"
    assert "audio_b64" not in tmpl  # must not include audio in list


@pytest.mark.asyncio
async def test_list_templates_character_filter(client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
    char1 = await _create_character(client, auth_headers, "Char1")
    char2 = await _create_character(client, auth_headers, "Char2")

    draft1 = await _create_ready_draft(client, auth_headers, char1, db_session)
    draft2 = await _create_ready_draft(client, auth_headers, char2, db_session)

    await _approve_draft(client, auth_headers, draft1, char1, "T1")
    await _approve_draft(client, auth_headers, draft2, char2, "T2")

    resp = await client.get(f"/api/v1/templates?character_id={char1}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["templates"][0]["character_id"] == char1


@pytest.mark.asyncio
async def test_list_templates_preset_type_filter(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    char_id = await _create_character(client, auth_headers)

    mode_draft_id = await _create_ready_draft(client, auth_headers, char_id, db_session, preset_type="mode")
    await _approve_draft(client, auth_headers, mode_draft_id, char_id, "Mode Template")

    emotion_draft_id = await _create_ready_draft(client, auth_headers, char_id, db_session, preset_type="emotion")
    await _approve_draft(client, auth_headers, emotion_draft_id, char_id, "Emotion Template")

    resp_emotion = await client.get("/api/v1/templates?preset_type=emotion", headers=auth_headers)
    assert resp_emotion.json()["total"] == 1

    resp_mode = await client.get("/api/v1/templates?preset_type=mode", headers=auth_headers)
    assert resp_mode.json()["total"] == 1


@pytest.mark.asyncio
async def test_list_templates_invalid_preset_type(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/templates?preset_type=banana", headers=auth_headers)
    assert resp.status_code == 400


# ── GET /api/v1/templates/{template_id} ──────────────────────────────────────

@pytest.mark.asyncio
async def test_get_template_includes_audio(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    char_id = await _create_character(client, auth_headers)
    draft_id = await _create_ready_draft(client, auth_headers, char_id, db_session)
    tmpl_id = await _approve_draft(client, auth_headers, draft_id, char_id)

    resp = await client.get(f"/api/v1/templates/{tmpl_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["template"]
    assert "audio_b64" in data
    assert data["audio_b64"] is not None
    assert len(data["audio_b64"]) > 0


@pytest.mark.asyncio
async def test_get_template_not_found(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/templates/nonexistent-id", headers=auth_headers)
    assert resp.status_code == 404


# ── PATCH /api/v1/templates/{template_id} ────────────────────────────────────

@pytest.mark.asyncio
async def test_rename_template(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    char_id = await _create_character(client, auth_headers)
    draft_id = await _create_ready_draft(client, auth_headers, char_id, db_session)
    tmpl_id = await _approve_draft(client, auth_headers, draft_id, char_id, "Old Name")

    resp = await client.patch(
        f"/api/v1/templates/{tmpl_id}",
        json={"name": "New Name"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["template"]["name"] == "New Name"
    assert "audio_b64" not in resp.json()["template"]


@pytest.mark.asyncio
async def test_rename_template_empty_name(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    char_id = await _create_character(client, auth_headers)
    draft_id = await _create_ready_draft(client, auth_headers, char_id, db_session)
    tmpl_id = await _approve_draft(client, auth_headers, draft_id, char_id)

    resp = await client.patch(
        f"/api/v1/templates/{tmpl_id}",
        json={"name": "   "},
        headers=auth_headers,
    )
    assert resp.status_code == 400


# ── DELETE /api/v1/templates/{template_id} ───────────────────────────────────

@pytest.mark.asyncio
async def test_delete_template(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    char_id = await _create_character(client, auth_headers)
    draft_id = await _create_ready_draft(client, auth_headers, char_id, db_session)
    tmpl_id = await _approve_draft(client, auth_headers, draft_id, char_id)

    resp = await client.delete(f"/api/v1/templates/{tmpl_id}", headers=auth_headers)
    assert resp.status_code == 204

    get_resp = await client.get(f"/api/v1/templates/{tmpl_id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_template_does_not_delete_draft(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Deleting a template must NOT delete the source draft."""
    char_id = await _create_character(client, auth_headers)
    draft_id = await _create_ready_draft(client, auth_headers, char_id, db_session)
    tmpl_id = await _approve_draft(client, auth_headers, draft_id, char_id)

    await client.delete(f"/api/v1/templates/{tmpl_id}", headers=auth_headers)

    # Draft still accessible
    draft_resp = await client.get(f"/api/v1/drafts/{draft_id}", headers=auth_headers)
    assert draft_resp.status_code == 200
    assert draft_resp.json()["draft"]["status"] == "approved"


@pytest.mark.asyncio
async def test_delete_template_not_found(client: AsyncClient, auth_headers: dict):
    resp = await client.delete("/api/v1/templates/nonexistent-id", headers=auth_headers)
    assert resp.status_code == 404


# ── Isolation ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_templates_isolated_per_user(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    await client.post("/auth/register", json={"email": "c@c.com", "password": "password123"})
    login_resp = await client.post("/auth/login", json={"email": "c@c.com", "password": "password123"})
    headers_c = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    # User A creates a template
    char_a = await _create_character(client, auth_headers, "Char A")
    draft_a = await _create_ready_draft(client, auth_headers, char_a, db_session)
    await _approve_draft(client, auth_headers, draft_a, char_a, "A's Template")

    # User C has none
    resp_c = await client.get("/api/v1/templates", headers=headers_c)
    assert resp_c.json()["total"] == 0
