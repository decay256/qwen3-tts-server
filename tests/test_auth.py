"""Tests for auth module."""

import hmac
import time
import pytest


def test_sign_and_verify():
    from server.auth import sign_message, verify_message
    payload = {"type": "test", "data": "hello"}
    signed = sign_message(payload.copy())
    assert "_sig" in signed
    assert "_ts" in signed
    assert verify_message(signed) is True


def test_tampered_message():
    from server.auth import sign_message, verify_message
    payload = {"type": "test", "data": "hello"}
    signed = sign_message(payload.copy())
    signed["data"] = "tampered"
    assert verify_message(signed) is False


def test_missing_signature():
    from server.auth import verify_message
    assert verify_message({"type": "test", "_ts": int(time.time())}) is False


def test_expired_timestamp():
    from server.auth import sign_message, verify_message
    signed = sign_message({"type": "test"})
    signed["_ts"] = int(time.time()) - 600
    assert verify_message(signed) is False


def test_future_timestamp():
    from server.auth import sign_message, verify_message
    signed = sign_message({"type": "test"})
    signed["_ts"] = int(time.time()) + 600
    assert verify_message(signed) is False


def test_verify_token():
    from server.auth import verify_token
    assert verify_token("test-token-12345") is True
    assert verify_token("wrong-token") is False


def test_extract_api_key():
    from server.auth import extract_api_key
    assert extract_api_key({"Authorization": "Bearer my-key"}) == "my-key"
    assert extract_api_key({"authorization": "Bearer my-key"}) == "my-key"
    assert extract_api_key({"Authorization": "Basic foo"}) is None
    assert extract_api_key({}) is None


def test_auth_manager_authenticate():
    from server.auth import AuthManager
    mgr = AuthManager("secret-key")
    assert mgr.authenticate({"Authorization": "Bearer secret-key"}) == "secret-key"
    assert mgr.authenticate({"Authorization": "Bearer wrong"}) is None
    assert mgr.authenticate({}) is None


def test_auth_manager_verify_token():
    from server.auth import AuthManager
    mgr = AuthManager("secret-key")
    assert mgr.verify_token("secret-key") is True
    assert mgr.verify_token("wrong") is False


def test_auth_manager_cleanup_nonces():
    from server.auth import AuthManager
    mgr = AuthManager("key", max_age=1)
    mgr._seen_nonces["old"] = time.time() - 10
    mgr._seen_nonces["new"] = time.time()
    mgr.cleanup_nonces()
    assert "old" not in mgr._seen_nonces
    assert "new" in mgr._seen_nonces
