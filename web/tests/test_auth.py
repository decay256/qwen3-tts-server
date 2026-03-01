"""Tests for authentication routes."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register(client: AsyncClient):
    resp = await client.post("/auth/register", json={
        "email": "new@example.com",
        "password": "securepassword",
    })
    assert resp.status_code == 201
    assert resp.json()["message"] == "Account created. Check your email to verify."


@pytest.mark.asyncio
async def test_register_duplicate(client: AsyncClient):
    await client.post("/auth/register", json={
        "email": "dup@example.com",
        "password": "securepassword",
    })
    resp = await client.post("/auth/register", json={
        "email": "dup@example.com",
        "password": "securepassword",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_short_password(client: AsyncClient):
    resp = await client.post("/auth/register", json={
        "email": "short@example.com",
        "password": "short",
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    await client.post("/auth/register", json={
        "email": "login@example.com",
        "password": "securepassword",
    })
    resp = await client.post("/auth/login", json={
        "email": "login@example.com",
        "password": "securepassword",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await client.post("/auth/register", json={
        "email": "wrong@example.com",
        "password": "securepassword",
    })
    resp = await client.post("/auth/login", json={
        "email": "wrong@example.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent(client: AsyncClient):
    resp = await client.post("/auth/login", json={
        "email": "nobody@example.com",
        "password": "whatever",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient):
    await client.post("/auth/register", json={
        "email": "refresh@example.com",
        "password": "securepassword",
    })
    login_resp = await client.post("/auth/login", json={
        "email": "refresh@example.com",
        "password": "securepassword",
    })
    refresh_token = login_resp.json()["refresh_token"]

    resp = await client.post("/auth/refresh", json={
        "refresh_token": refresh_token,
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_refresh_invalid_token(client: AsyncClient):
    resp = await client.post("/auth/refresh", json={
        "refresh_token": "invalid.token.here",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_reset_request_doesnt_reveal_existence(client: AsyncClient):
    """Reset request always returns success regardless of email existence."""
    resp = await client.post("/auth/reset-request", json={
        "email": "nonexistent@example.com",
    })
    assert resp.status_code == 200
    assert "reset link has been sent" in resp.json()["message"]


@pytest.mark.asyncio
async def test_reset_confirm_invalid_token(client: AsyncClient):
    resp = await client.post("/auth/reset-confirm", json={
        "token": "invalid.token",
        "new_password": "newpassword123",
    })
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Auto-verify email in non-prod (Sprint 3 — issue #26)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_auto_verify_in_non_prod(client: AsyncClient, monkeypatch):
    """In non-production env, registration auto-verifies the account."""
    from web.app.routes import auth as auth_module
    from web.app.core.config import settings

    monkeypatch.setattr(settings, "env", "development")
    resp = await client.post("/auth/register", json={
        "email": "autoverify@example.com",
        "password": "securepassword",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "auto-verified" in data["message"]
    assert "development" in data["message"]


@pytest.mark.asyncio
async def test_register_no_auto_verify_in_production(client: AsyncClient, monkeypatch):
    """In production env, registration does NOT auto-verify — sends email instead."""
    from web.app.core.config import settings

    monkeypatch.setattr(settings, "env", "production")
    resp = await client.post("/auth/register", json={
        "email": "nonauto@example.com",
        "password": "securepassword",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "verify" in data["message"].lower()
    assert "auto-verified" not in data["message"]
