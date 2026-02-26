"""Tests for security utilities (JWT, password hashing)."""

import pytest
from web.app.core.security import (
    create_access_token,
    create_refresh_token,
    create_reset_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_and_verify():
    hashed = hash_password("mysecret")
    assert hashed != "mysecret"
    assert verify_password("mysecret", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token():
    token = create_access_token("user-123")
    subject = decode_token(token, expected_type="access")
    assert subject == "user-123"


def test_refresh_token():
    token = create_refresh_token("user-456")
    subject = decode_token(token, expected_type="refresh")
    assert subject == "user-456"
    # Should not validate as access token
    assert decode_token(token, expected_type="access") is None


def test_reset_token():
    token = create_reset_token("user-789")
    subject = decode_token(token, expected_type="reset")
    assert subject == "user-789"
    assert decode_token(token, expected_type="access") is None


def test_invalid_token():
    assert decode_token("garbage.token.here") is None


def test_wrong_type_rejected():
    token = create_access_token("user-1")
    assert decode_token(token, expected_type="refresh") is None
