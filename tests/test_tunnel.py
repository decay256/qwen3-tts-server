"""Tests for tunnel and auth logic."""

import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set a test token
os.environ["AUTH_TOKEN"] = "test-token-12345"


class TestAuth(unittest.TestCase):
    def test_sign_and_verify(self):
        from server.auth import sign_message, verify_message
        payload = {"type": "test", "data": "hello"}
        signed = sign_message(payload.copy())
        self.assertIn("_sig", signed)
        self.assertIn("_ts", signed)
        self.assertTrue(verify_message(signed))

    def test_tampered_message(self):
        from server.auth import sign_message, verify_message
        payload = {"type": "test", "data": "hello"}
        signed = sign_message(payload.copy())
        signed["data"] = "tampered"
        self.assertFalse(verify_message(signed))

    def test_missing_sig(self):
        from server.auth import verify_message
        self.assertFalse(verify_message({"type": "test", "_ts": int(time.time())}))

    def test_expired_timestamp(self):
        from server.auth import sign_message, verify_message
        payload = {"type": "test"}
        signed = sign_message(payload.copy())
        signed["_ts"] = int(time.time()) - 600  # 10 min ago
        # Re-sign with old timestamp won't match
        self.assertFalse(verify_message(signed))

    def test_verify_token(self):
        from server.auth import verify_token
        self.assertTrue(verify_token("test-token-12345"))
        self.assertFalse(verify_token("wrong-token"))


if __name__ == "__main__":
    unittest.main()
