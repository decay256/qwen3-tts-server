"""Tests for configuration routes."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_config(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/config", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "tts_relay_url" in data
    assert "llm_provider" in data
    assert "llm_model" in data
    assert "has_openai_key" in data


@pytest.mark.asyncio
async def test_update_config(client: AsyncClient, auth_headers: dict):
    resp = await client.patch("/api/v1/config", json={
        "llm_provider": "anthropic",
        "llm_model": "claude-sonnet-4-20250514",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["llm_provider"] == "anthropic"
    assert resp.json()["llm_model"] == "claude-sonnet-4-20250514"


@pytest.mark.asyncio
async def test_update_config_invalid_provider(client: AsyncClient, auth_headers: dict):
    resp = await client.patch("/api/v1/config", json={
        "llm_provider": "invalid",
    }, headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_config_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/v1/config")
    assert resp.status_code in (401, 403)
