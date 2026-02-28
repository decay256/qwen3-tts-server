"""Tests for preset routes — /api/v1/presets."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_presets_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/presets")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_presets_returns_emotions_and_modes(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/presets", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "emotions" in data
    assert "modes" in data
    assert len(data["emotions"]) > 0
    assert len(data["modes"]) > 0


@pytest.mark.asyncio
async def test_preset_emotion_structure(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/presets", headers=auth_headers)
    emotion = resp.json()["emotions"][0]
    assert emotion["type"] == "emotion"
    assert "name" in emotion
    assert "instruct_medium" in emotion
    assert "instruct_intense" in emotion
    assert "ref_text_medium" in emotion
    assert "ref_text_intense" in emotion
    assert "tags" in emotion


@pytest.mark.asyncio
async def test_preset_mode_structure(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/presets", headers=auth_headers)
    mode = resp.json()["modes"][0]
    assert mode["type"] == "mode"
    assert "name" in mode
    assert "instruct" in mode
    assert "ref_text" in mode
    assert "tags" in mode


@pytest.mark.asyncio
async def test_preset_emotion_count(client: AsyncClient, auth_headers: dict):
    """Should have 9 emotions (joy, sadness, anger, fear, surprise, disgust, tenderness, awe, mischief)."""
    resp = await client.get("/api/v1/presets", headers=auth_headers)
    assert len(resp.json()["emotions"]) == 9


@pytest.mark.asyncio
async def test_preset_mode_count(client: AsyncClient, auth_headers: dict):
    """Should have 13 modes."""
    resp = await client.get("/api/v1/presets", headers=auth_headers)
    assert len(resp.json()["modes"]) == 13
