"""Tests for character management routes."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_character(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/v1/characters", json={
        "name": "Kira",
        "base_description": "Adult woman, low-mid pitch, husky voice",
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Kira"
    assert data["base_description"] == "Adult woman, low-mid pitch, husky voice"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_characters(client: AsyncClient, auth_headers: dict):
    await client.post("/api/v1/characters", json={
        "name": "Kira", "base_description": "Husky woman",
    }, headers=auth_headers)
    await client.post("/api/v1/characters", json={
        "name": "Marcus", "base_description": "Young man, tenor",
    }, headers=auth_headers)

    resp = await client.get("/api/v1/characters", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


@pytest.mark.asyncio
async def test_get_character(client: AsyncClient, auth_headers: dict):
    create_resp = await client.post("/api/v1/characters", json={
        "name": "Kira", "base_description": "Husky woman",
    }, headers=auth_headers)
    char_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/characters/{char_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Kira"


@pytest.mark.asyncio
async def test_get_nonexistent_character(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/characters/nonexistent-id", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_character(client: AsyncClient, auth_headers: dict):
    create_resp = await client.post("/api/v1/characters", json={
        "name": "Kira", "base_description": "Husky woman",
    }, headers=auth_headers)
    char_id = create_resp.json()["id"]

    resp = await client.patch(f"/api/v1/characters/{char_id}", json={
        "name": "Kira v2",
        "base_description": "Adult woman, deeper voice",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Kira v2"
    assert resp.json()["base_description"] == "Adult woman, deeper voice"


@pytest.mark.asyncio
async def test_delete_character(client: AsyncClient, auth_headers: dict):
    create_resp = await client.post("/api/v1/characters", json={
        "name": "Kira", "base_description": "Husky woman",
    }, headers=auth_headers)
    char_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/v1/characters/{char_id}", headers=auth_headers)
    assert resp.status_code == 204

    get_resp = await client.get(f"/api/v1/characters/{char_id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_access(client: AsyncClient):
    resp = await client.get("/api/v1/characters")
    assert resp.status_code in (401, 403)  # No auth header


@pytest.mark.asyncio
async def test_user_isolation(client: AsyncClient):
    """Users can only see their own characters."""
    # Create user 1
    await client.post("/auth/register", json={
        "email": "user1@example.com", "password": "password123",
    })
    login1 = await client.post("/auth/login", json={
        "email": "user1@example.com", "password": "password123",
    })
    headers1 = {"Authorization": f"Bearer {login1.json()['access_token']}"}

    # Create user 2
    await client.post("/auth/register", json={
        "email": "user2@example.com", "password": "password123",
    })
    login2 = await client.post("/auth/login", json={
        "email": "user2@example.com", "password": "password123",
    })
    headers2 = {"Authorization": f"Bearer {login2.json()['access_token']}"}

    # User 1 creates a character
    await client.post("/api/v1/characters", json={
        "name": "Private", "base_description": "Secret voice",
    }, headers=headers1)

    # User 2 should not see it
    resp = await client.get("/api/v1/characters", headers=headers2)
    assert len(resp.json()) == 0
