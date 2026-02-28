"""Tests for preset routes — /api/v1/presets."""

import pytest
from httpx import AsyncClient


# ── Existing GET tests ──────────────────────────────────────────────────────


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
    assert "is_builtin" in emotion


@pytest.mark.asyncio
async def test_preset_mode_structure(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/presets", headers=auth_headers)
    mode = resp.json()["modes"][0]
    assert mode["type"] == "mode"
    assert "name" in mode
    assert "instruct" in mode
    assert "ref_text" in mode
    assert "tags" in mode
    assert "is_builtin" in mode


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


@pytest.mark.asyncio
async def test_builtin_presets_have_is_builtin_true(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/presets", headers=auth_headers)
    data = resp.json()
    for e in data["emotions"]:
        assert e["is_builtin"] is True
    for m in data["modes"]:
        assert m["is_builtin"] is True


# ── Emotion CRUD ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_emotion_preset_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/presets/emotions", json={
        "name": "test_emo",
        "instruct_medium": "mildly scared",
        "instruct_intense": "screaming in fear",
        "ref_text_medium": "Something's not right here.",
        "ref_text_intense": "Get away from me!",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_emotion_preset(client: AsyncClient, auth_headers: dict):
    payload = {
        "name": "nostalgic",
        "instruct_medium": "gently nostalgic, warmly remembering the past",
        "instruct_intense": "overwhelmed with nostalgia, voice cracking with memory",
        "ref_text_medium": "I remember when we used to come here every summer.",
        "ref_text_intense": "This place hasn't changed at all. I can still see us, kids again, running through these halls.",
        "tags": ["nostalgic", "memories"],
    }
    resp = await client.post("/api/v1/presets/emotions", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "nostalgic"
    assert data["type"] == "emotion"
    assert data["is_builtin"] is False
    assert data["instruct_medium"] == payload["instruct_medium"]
    assert data["tags"] == ["nostalgic", "memories"]


@pytest.mark.asyncio
async def test_create_emotion_preset_appears_in_get(client: AsyncClient, auth_headers: dict):
    """Custom preset should appear in GET /api/v1/presets after creation."""
    await client.post("/api/v1/presets/emotions", json={
        "name": "wistful",
        "instruct_medium": "wistful, bittersweet",
        "instruct_intense": "deeply wistful, voice heavy with longing",
        "ref_text_medium": "Those were simpler times.",
        "ref_text_intense": "I'd give anything to go back, just for a moment.",
    }, headers=auth_headers)

    resp = await client.get("/api/v1/presets", headers=auth_headers)
    names = [e["name"] for e in resp.json()["emotions"]]
    assert "wistful" in names


@pytest.mark.asyncio
async def test_create_emotion_preset_conflict(client: AsyncClient, auth_headers: dict):
    """Creating a duplicate custom preset name returns 409."""
    payload = {
        "name": "duplicate_emo",
        "instruct_medium": "a",
        "instruct_intense": "b",
        "ref_text_medium": "c",
        "ref_text_intense": "d",
    }
    resp1 = await client.post("/api/v1/presets/emotions", json=payload, headers=auth_headers)
    assert resp1.status_code == 201
    resp2 = await client.post("/api/v1/presets/emotions", json=payload, headers=auth_headers)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_create_emotion_preset_empty_name(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/v1/presets/emotions", json={
        "name": "  ",
        "instruct_medium": "a",
        "instruct_intense": "b",
        "ref_text_medium": "c",
        "ref_text_intense": "d",
    }, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_custom_emotion_preset(client: AsyncClient, auth_headers: dict):
    """PATCH updates a custom emotion preset."""
    await client.post("/api/v1/presets/emotions", json={
        "name": "edit_me",
        "instruct_medium": "original instruct",
        "instruct_intense": "original intense",
        "ref_text_medium": "original text",
        "ref_text_intense": "original intense text",
    }, headers=auth_headers)

    resp = await client.patch("/api/v1/presets/emotions/edit_me", json={
        "instruct_medium": "updated instruct",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["instruct_medium"] == "updated instruct"
    assert resp.json()["instruct_intense"] == "original intense"  # unchanged


@pytest.mark.asyncio
async def test_update_builtin_emotion_creates_override(client: AsyncClient, auth_headers: dict):
    """PATCHing a built-in emotion creates a custom override, not modifying the built-in."""
    resp = await client.patch("/api/v1/presets/emotions/happy", json={
        "instruct_medium": "custom happy instruct",
    }, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "happy"
    assert data["instruct_medium"] == "custom happy instruct"
    assert data["is_builtin"] is False

    # The override should appear in GET with custom value
    get_resp = await client.get("/api/v1/presets", headers=auth_headers)
    happy = next(e for e in get_resp.json()["emotions"] if e["name"] == "happy")
    assert happy["instruct_medium"] == "custom happy instruct"
    assert happy["is_builtin"] is False


@pytest.mark.asyncio
async def test_update_nonexistent_emotion_returns_404(client: AsyncClient, auth_headers: dict):
    resp = await client.patch("/api/v1/presets/emotions/nonexistent_emo_xyz", json={
        "instruct_medium": "whatever",
    }, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_custom_emotion_preset(client: AsyncClient, auth_headers: dict):
    await client.post("/api/v1/presets/emotions", json={
        "name": "delete_me",
        "instruct_medium": "x",
        "instruct_intense": "y",
        "ref_text_medium": "z",
        "ref_text_intense": "w",
    }, headers=auth_headers)

    resp = await client.delete("/api/v1/presets/emotions/delete_me", headers=auth_headers)
    assert resp.status_code == 204

    # Should no longer appear in GET
    get_resp = await client.get("/api/v1/presets", headers=auth_headers)
    names = [e["name"] for e in get_resp.json()["emotions"]]
    assert "delete_me" not in names


@pytest.mark.asyncio
async def test_delete_nonexistent_emotion_returns_404(client: AsyncClient, auth_headers: dict):
    resp = await client.delete("/api/v1/presets/emotions/does_not_exist_xyz", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_builtin_emotion_returns_404(client: AsyncClient, auth_headers: dict):
    """Cannot delete built-in emotion presets — they don't exist in custom_presets table."""
    resp = await client.delete("/api/v1/presets/emotions/happy", headers=auth_headers)
    assert resp.status_code == 404


# ── Mode CRUD ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_mode_preset_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/presets/modes", json={
        "name": "test_mode",
        "instruct": "whispering softly",
        "ref_text": "Can you hear me?",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_mode_preset(client: AsyncClient, auth_headers: dict):
    payload = {
        "name": "mourning",
        "instruct": "mourning, deeply sorrowful, slow and heavy",
        "ref_text": "We gather here today to remember someone who meant so much to us.",
        "tags": ["mourning", "funeral"],
    }
    resp = await client.post("/api/v1/presets/modes", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "mourning"
    assert data["type"] == "mode"
    assert data["is_builtin"] is False
    assert data["instruct"] == payload["instruct"]


@pytest.mark.asyncio
async def test_create_mode_preset_appears_in_get(client: AsyncClient, auth_headers: dict):
    await client.post("/api/v1/presets/modes", json={
        "name": "conspiring",
        "instruct": "conspiratorial, hushed and urgent",
        "ref_text": "Don't tell anyone, but I know what really happened.",
    }, headers=auth_headers)

    resp = await client.get("/api/v1/presets", headers=auth_headers)
    names = [m["name"] for m in resp.json()["modes"]]
    assert "conspiring" in names


@pytest.mark.asyncio
async def test_create_mode_preset_conflict(client: AsyncClient, auth_headers: dict):
    payload = {"name": "dup_mode", "instruct": "a", "ref_text": "b"}
    r1 = await client.post("/api/v1/presets/modes", json=payload, headers=auth_headers)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/presets/modes", json=payload, headers=auth_headers)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_update_custom_mode_preset(client: AsyncClient, auth_headers: dict):
    await client.post("/api/v1/presets/modes", json={
        "name": "edit_mode",
        "instruct": "original mode instruct",
        "ref_text": "original mode text",
    }, headers=auth_headers)

    resp = await client.patch("/api/v1/presets/modes/edit_mode", json={
        "instruct": "updated mode instruct",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["instruct"] == "updated mode instruct"
    assert resp.json()["ref_text"] == "original mode text"


@pytest.mark.asyncio
async def test_update_builtin_mode_creates_override(client: AsyncClient, auth_headers: dict):
    """PATCHing a built-in mode creates a custom override."""
    # Get the first built-in mode name
    get_resp = await client.get("/api/v1/presets", headers=auth_headers)
    first_mode = get_resp.json()["modes"][0]["name"]

    resp = await client.patch(f"/api/v1/presets/modes/{first_mode}", json={
        "instruct": "custom override instruct",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["instruct"] == "custom override instruct"
    assert resp.json()["is_builtin"] is False


@pytest.mark.asyncio
async def test_update_nonexistent_mode_returns_404(client: AsyncClient, auth_headers: dict):
    resp = await client.patch("/api/v1/presets/modes/nonexistent_mode_xyz", json={
        "instruct": "whatever",
    }, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_custom_mode_preset(client: AsyncClient, auth_headers: dict):
    await client.post("/api/v1/presets/modes", json={
        "name": "delete_mode",
        "instruct": "x",
        "ref_text": "y",
    }, headers=auth_headers)

    resp = await client.delete("/api/v1/presets/modes/delete_mode", headers=auth_headers)
    assert resp.status_code == 204

    get_resp = await client.get("/api/v1/presets", headers=auth_headers)
    names = [m["name"] for m in get_resp.json()["modes"]]
    assert "delete_mode" not in names


@pytest.mark.asyncio
async def test_delete_nonexistent_mode_returns_404(client: AsyncClient, auth_headers: dict):
    resp = await client.delete("/api/v1/presets/modes/does_not_exist_xyz", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_builtin_mode_returns_404(client: AsyncClient, auth_headers: dict):
    """Cannot delete built-in mode presets."""
    get_resp = await client.get("/api/v1/presets", headers=auth_headers)
    first_mode = get_resp.json()["modes"][0]["name"]
    resp = await client.delete(f"/api/v1/presets/modes/{first_mode}", headers=auth_headers)
    assert resp.status_code == 404


# ── User isolation ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_custom_presets_are_user_scoped(client: AsyncClient, auth_headers: dict):
    """Presets created by one user should not be visible to another."""
    # Create preset as user 1
    await client.post("/api/v1/presets/emotions", json={
        "name": "user_only_preset",
        "instruct_medium": "a",
        "instruct_intense": "b",
        "ref_text_medium": "c",
        "ref_text_intense": "d",
    }, headers=auth_headers)

    # Register and login as user 2
    await client.post("/auth/register", json={
        "email": "user2@example.com",
        "password": "password123",
    })
    resp2 = await client.post("/auth/login", json={
        "email": "user2@example.com",
        "password": "password123",
    })
    headers2 = {"Authorization": f"Bearer {resp2.json()['access_token']}"}

    get_resp = await client.get("/api/v1/presets", headers=headers2)
    names = [e["name"] for e in get_resp.json()["emotions"]]
    assert "user_only_preset" not in names


@pytest.mark.asyncio
async def test_custom_override_only_applies_to_creating_user(client: AsyncClient, auth_headers: dict):
    """Overriding a built-in preset should only affect the creating user's view."""
    await client.patch("/api/v1/presets/emotions/happy", json={
        "instruct_medium": "user1 custom happy",
    }, headers=auth_headers)

    # User 2 should still see the original built-in
    await client.post("/auth/register", json={
        "email": "user3@example.com",
        "password": "password123",
    })
    resp2 = await client.post("/auth/login", json={
        "email": "user3@example.com",
        "password": "password123",
    })
    headers2 = {"Authorization": f"Bearer {resp2.json()['access_token']}"}

    get_resp = await client.get("/api/v1/presets", headers=headers2)
    happy = next(e for e in get_resp.json()["emotions"] if e["name"] == "happy")
    assert happy["instruct_medium"] != "user1 custom happy"
    assert happy["is_builtin"] is True
