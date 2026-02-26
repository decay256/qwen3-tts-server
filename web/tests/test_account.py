"""Tests for account management routes."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_account(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/account", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@example.com"
    assert "id" in data


@pytest.mark.asyncio
async def test_change_password(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/v1/account/change-password", json={
        "current_password": "testpassword123",
        "new_password": "newpassword456",
    }, headers=auth_headers)
    assert resp.status_code == 200

    # Login with new password
    resp = await client.post("/auth/login", json={
        "email": "test@example.com",
        "password": "newpassword456",
    })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_current(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/v1/account/change-password", json={
        "current_password": "wrongpassword",
        "new_password": "newpassword456",
    }, headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_change_email(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/v1/account/change-email", json={
        "email": "newemail@example.com",
        "password": "testpassword123",
    }, headers=auth_headers)
    assert resp.status_code == 200

    # Login with new email
    resp = await client.post("/auth/login", json={
        "email": "newemail@example.com",
        "password": "testpassword123",
    })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_delete_account(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/v1/account/delete", json={
        "password": "testpassword123",
    }, headers=auth_headers)
    assert resp.status_code == 200

    # Can't login anymore
    resp = await client.post("/auth/login", json={
        "email": "test@example.com",
        "password": "testpassword123",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_account_wrong_password(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/v1/account/delete", json={
        "password": "wrongpassword",
    }, headers=auth_headers)
    assert resp.status_code == 400
