"""Tests for TTS engine (run on GPU machine)."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestChunking(unittest.TestCase):
    def test_short_text(self):
        from server.tts_engine import chunk_text
        chunks = chunk_text("Hello world.", max_chars=500)
        self.assertEqual(len(chunks), 1)

    def test_long_text(self):
        from server.tts_engine import chunk_text
        text = "First sentence. Second sentence. Third sentence. " * 20
        chunks = chunk_text(text, max_chars=100)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 200)  # some overflow OK

    def test_empty(self):
        from server.tts_engine import chunk_text
        chunks = chunk_text("")
        self.assertEqual(chunks, [""])


class TestWavConversion(unittest.TestCase):
    def test_wav_format(self):
        from server.tts_engine import wav_to_format
        wav = np.random.randn(16000).astype(np.float32)
        result = wav_to_format(wav, 16000, "wav")
        self.assertTrue(len(result) > 0)
        # WAV header starts with RIFF
        self.assertEqual(result[:4], b"RIFF")


class TestEngineInit(unittest.TestCase):
    def test_engine_not_loaded(self):
        from server.tts_engine import TTSEngine
        engine = TTSEngine()
        self.assertFalse(engine.is_loaded)

    def test_list_voices_empty(self):
        from server.tts_engine import TTSEngine
        engine = TTSEngine()
        engine._loaded = True
        voices = engine.list_voices()
        self.assertIsInstance(voices, list)


if __name__ == "__main__":
    unittest.main()
