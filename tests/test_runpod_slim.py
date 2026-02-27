"""End-to-end tests for the slim RunPod handler.

Tests the full handler dispatch with a mocked TTS engine.
Validates: status, voice design, clone synthesis, clone prompt create/synthesize.
"""
import base64
import io
import os
import struct
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def make_wav_bytes(duration_s=0.5, sample_rate=24000):
    """Generate a minimal valid WAV file (silence)."""
    num_samples = int(sample_rate * duration_s)
    data_size = num_samples * 2  # 16-bit mono
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", data_size,
    )
    return header + b"\x00" * data_size


class MockTTSEngine:
    """Mock TTS engine that returns silent WAV data."""

    def __init__(self):
        self._models = {"voice_design": True, "base": True}

    def load_models(self):
        pass

    def get_loaded_models(self):
        return list(self._models.keys())

    def synthesize_voice_design(self, text, instruct, language="English"):
        wav = make_wav_bytes(0.5)
        return wav, 0.5

    def synthesize_clone(self, ref_audio, ref_text, text, language="Auto"):
        wav = make_wav_bytes(0.3)
        return wav, 0.3

    def create_clone_prompt(self, ref_audio, name, ref_text=""):
        import torch
        return {"codes": torch.zeros(1, 10), "name": name}

    def synthesize_with_clone_prompt(self, prompt_data, text, language="Auto"):
        wav = make_wav_bytes(0.4)
        return wav, 0.4


class TestRunpodSlimHandler(unittest.TestCase):
    """Test the handler function end-to-end with mocked engine."""

    @classmethod
    def setUpClass(cls):
        """Import handler with mocked engine."""
        cls.mock_engine = MockTTSEngine()
        # Mock runpod before importing
        sys.modules["runpod"] = MagicMock()
        sys.modules["runpod.serverless"] = MagicMock()
        with patch.dict(os.environ, {"API_KEY": "test-key-123"}):
            import server.runpod_slim as slim
            slim.engine = cls.mock_engine
            slim.init_done = True
            slim.init_error = None
            cls.handler = slim.handler
            cls.slim = slim

    def _call(self, endpoint, body=None, api_key="test-key-123"):
        event = {
            "input": {
                "endpoint": endpoint,
                "body": body or {},
                "api_key": api_key,
            }
        }
        return self.slim.handler(event)

    def test_status(self):
        # Patch env for this test
        with patch.dict(os.environ, {"API_KEY": "test-key-123"}):
            result = self._call("/api/v1/status")
        self.assertEqual(result["status"], "running")
        self.assertIn("voice_design", result["models_loaded"])

    def test_bad_api_key(self):
        with patch.dict(os.environ, {"API_KEY": "test-key-123"}):
            result = self._call("/api/v1/status", api_key="wrong")
        self.assertIn("error", result)
        self.assertIn("Invalid", result["error"])

    def test_unknown_endpoint(self):
        with patch.dict(os.environ, {"API_KEY": "test-key-123"}):
            result = self._call("/api/v1/nonexistent")
        self.assertIn("error", result)
        self.assertIn("Unknown", result["error"])

    def test_voice_design(self):
        with patch.dict(os.environ, {"API_KEY": "test-key-123"}):
            result = self._call("/api/v1/voices/design", {
                "text": "Hello world",
                "instruct": "Young woman, bright voice",
            })
        self.assertIn("audio", result)
        self.assertEqual(result["format"], "wav")
        self.assertGreater(result["duration_s"], 0)
        # Verify audio is valid base64
        audio_bytes = base64.b64decode(result["audio"])
        self.assertTrue(audio_bytes[:4] == b"RIFF")

    def test_clone_synthesis(self):
        ref_wav = make_wav_bytes(0.2)
        with patch.dict(os.environ, {"API_KEY": "test-key-123"}):
            result = self._call("/api/v1/tts/synthesize", {
                "text": "Test clone",
                "ref_audio": base64.b64encode(ref_wav).decode(),
                "ref_text": "Reference transcript",
            })
        self.assertIn("audio", result)
        self.assertEqual(result["format"], "wav")

    def test_clone_prompt_create(self):
        import torch
        ref_wav = make_wav_bytes(0.2)
        with patch.dict(os.environ, {"API_KEY": "test-key-123"}):
            result = self._call("/api/v1/voices/clone-prompt/create", {
                "audio": base64.b64encode(ref_wav).decode(),
                "ref_text": "Hello",
                "name": "test_voice",
            })
        self.assertIn("prompt_data", result)
        self.assertEqual(result["name"], "test_voice")
        # Verify prompt can be deserialized
        prompt_bytes = base64.b64decode(result["prompt_data"])
        prompt = torch.load(io.BytesIO(prompt_bytes), weights_only=False)
        self.assertIn("codes", prompt)

    def test_clone_prompt_synthesize(self):
        import torch
        # First create a prompt
        prompt_data = {"codes": torch.zeros(1, 10), "name": "test"}
        buf = io.BytesIO()
        torch.save(prompt_data, buf)
        prompt_b64 = base64.b64encode(buf.getvalue()).decode()

        with patch.dict(os.environ, {"API_KEY": "test-key-123"}):
            result = self._call("/api/v1/tts/clone-prompt/synthesize", {
                "prompt_data": prompt_b64,
                "text": "Synthesize this",
            })
        self.assertIn("audio", result)
        self.assertEqual(result["format"], "wav")

    def test_no_api_key_required_when_not_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("API_KEY", None)
            result = self._call("/api/v1/status", api_key="")
        self.assertEqual(result["status"], "running")

    def test_voice_design_missing_fields(self):
        with patch.dict(os.environ, {"API_KEY": "test-key-123"}):
            result = self._call("/api/v1/voices/design", {})
        self.assertIn("error", result)


class TestHandlerLazyInit(unittest.TestCase):
    """Test that lazy init triggers correctly."""

    def test_lazy_init_called_when_engine_none(self):
        sys.modules["runpod"] = MagicMock()
        sys.modules["runpod.serverless"] = MagicMock()
        import server.runpod_slim as slim
        # Save original state
        orig_engine = slim.engine
        orig_done = slim.init_done

        try:
            slim.engine = None
            slim.init_done = False
            slim.init_error = None

            # Mock init to just set the mock engine
            mock_engine = MockTTSEngine()
            def fake_init():
                slim.engine = mock_engine
                slim.init_done = True

            with patch.object(slim, "init", side_effect=fake_init):
                with patch.dict(os.environ, {"API_KEY": ""}):
                    result = slim.handler({"input": {"endpoint": "/api/v1/status"}})

            self.assertEqual(result["status"], "running")
        finally:
            slim.engine = orig_engine
            slim.init_done = orig_done


if __name__ == "__main__":
    unittest.main()
