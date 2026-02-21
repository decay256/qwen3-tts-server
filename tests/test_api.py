"""Integration tests — only run with a live bridge + GPU tunnel.
Skipped by default when AUTH_TOKEN is the test token."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

BRIDGE_URL = os.getenv("TEST_BRIDGE_URL", "http://localhost:8766")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")


@unittest.skipUnless(
    AUTH_TOKEN and AUTH_TOKEN != "test-token-12345",
    "Skipped: set AUTH_TOKEN and TEST_BRIDGE_URL for integration tests",
)
class TestBridgeAPI(unittest.TestCase):
    """Integration tests — run with bridge + GPU tunnel active."""

    def _headers(self):
        return {"Authorization": f"Bearer {AUTH_TOKEN}", "Content-Type": "application/json"}

    def test_health(self):
        import urllib.request
        req = urllib.request.Request(f"{BRIDGE_URL}/api/v1/status")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            self.assertIn("relay", data)


if __name__ == "__main__":
    unittest.main()
