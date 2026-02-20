"""Authentication and message verification."""

import hashlib
import hmac
import time
import json
import logging

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
