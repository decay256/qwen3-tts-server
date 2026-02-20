"""End-to-end API tests (requires running bridge + tunnel)."""

import base64
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# These tests require a running bridge server
BRIDGE_URL = os.getenv("TEST_BRIDGE_URL", "http://localhost:8766")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")


@unittest.skipUnless(AUTH_TOKEN, "AUTH_TOKEN not set — skipping integration tests")
class TestBridgeAPI(unittest.TestCase):
    """Integration tests — run with bridge + GPU tunnel active."""

    def _headers(self):
        return {"Authorization": f"Bearer {AUTH_TOKEN}", "Content-Type": "application/json"}

    def test_health(self):
        import urllib.request
        req = urllib.request.Request(f"{BRIDGE_URL}/api/tts/health")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            self.assertIn("status", data)

    def test_voices(self):
        import urllib.request
        req = urllib.request.Request(
            f"{BRIDGE_URL}/api/tts/voices",
            headers=self._headers(),
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            self.assertIsInstance(data, list)

    def test_generate_voice_design(self):
        import urllib.request
        body = json.dumps({
            "text": "Hello, this is a test of the text to speech system.",
            "voice_config": {
                "description": "A warm male narrator voice, deep and clear",
                "language": "English",
            },
            "output_format": "wav",
        }).encode()
        req = urllib.request.Request(
            f"{BRIDGE_URL}/api/tts/generate",
            data=body,
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            audio = resp.read()
            self.assertGreater(len(audio), 1000)
            # Check WAV header
            self.assertEqual(audio[:4], b"RIFF")


if __name__ == "__main__":
    unittest.main()
