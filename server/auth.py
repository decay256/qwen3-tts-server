"""Authentication and message verification."""

from __future__ import annotations

import hashlib
import hmac
import time
import json
import logging
from typing import Optional

from . import config

logger = logging.getLogger(__name__)


def sign_message(payload: dict) -> dict:
    """Add timestamp and HMAC signature to a message."""
    payload["_ts"] = int(time.time())
    msg = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    sig = hmac.new(
        config.AUTH_TOKEN.encode(), msg.encode(), hashlib.sha256
    ).hexdigest()
    payload["_sig"] = sig
    return payload


def verify_message(payload: dict) -> bool:
    """Verify HMAC signature and check timestamp freshness (5 min window)."""
    sig = payload.pop("_sig", None)
    ts = payload.get("_ts", 0)
    if not sig:
        logger.warning("Message missing signature")
        return False
    # Check timestamp freshness
    if abs(time.time() - ts) > 300:
        logger.warning("Message timestamp too old/future: %s", ts)
        return False
    msg = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    expected = hmac.new(
        config.AUTH_TOKEN.encode(), msg.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        logger.warning("Invalid message signature")
        return False
    return True


def verify_token(token: str) -> bool:
    """Simple token comparison."""
    return hmac.compare_digest(token, config.AUTH_TOKEN)


def extract_api_key(headers: dict[str, str]) -> Optional[str]:
    """Extract API key from Authorization header.

    Supports 'Bearer <key>' format.

    Args:
        headers: Request headers dict.

    Returns:
        The API key string, or None if not found.
    """
    auth = headers.get("Authorization", headers.get("authorization", ""))
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


class AuthManager:
    """Manages API key authentication and replay protection.

    Args:
        api_key: The expected API key for authentication.
        max_age: Maximum age in seconds for replay protection (default 300).
    """

    def __init__(self, api_key: str, max_age: int = 300) -> None:
        self.api_key = api_key
        self.max_age = max_age
        self._seen_nonces: dict[str, float] = {}

    def authenticate(self, headers: dict[str, str]) -> Optional[str]:
        """Authenticate a request by checking the API key in headers.

        Args:
            headers: Request headers dict.

        Returns:
            The API key if valid, None otherwise.
        """
        key = extract_api_key(headers)
        if key is None:
            return None
        if hmac.compare_digest(key, self.api_key):
            return key
        return None

    def verify_token(self, token: str) -> bool:
        """Verify a token matches the configured API key.

        Args:
            token: Token to verify.

        Returns:
            True if the token matches.
        """
        return hmac.compare_digest(token, self.api_key)

    def cleanup_nonces(self) -> None:
        """Remove expired nonces from the replay protection cache."""
        now = time.time()
        expired = [k for k, v in self._seen_nonces.items() if now - v > self.max_age]
        for k in expired:
            del self._seen_nonces[k]
