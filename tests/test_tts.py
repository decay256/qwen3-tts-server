"""Tests for TTS engine (no GPU needed — mocked)."""

import os
import sys
import pytest
import numpy as np


class TestChunking:
    def test_short_text(self):
        from server.tts_engine import chunk_text
        chunks = chunk_text("Hello world.", max_chars=500)
        assert len(chunks) == 1

    def test_long_text(self):
        from server.tts_engine import chunk_text
        text = "First sentence. Second sentence. Third sentence. " * 20
        chunks = chunk_text(text, max_chars=100)
        assert len(chunks) > 1

    def test_empty(self):
        from server.tts_engine import chunk_text
        chunks = chunk_text("")
        assert chunks == [""]

    def test_single_long_sentence(self):
        from server.tts_engine import chunk_text
        text = "A" * 1000
        chunks = chunk_text(text, max_chars=500)
        assert len(chunks) >= 1


class TestWavConversion:
    def test_wav_format(self):
        from server.tts_engine import wav_to_format
        wav = np.random.randn(16000).astype(np.float32)
        result = wav_to_format(wav, 16000, "wav")
        assert len(result) > 0
        assert result[:4] == b"RIFF"


class TestEngineInit:
    def test_engine_not_loaded(self):
        from server.tts_engine import TTSEngine
        engine = TTSEngine()
        assert engine.is_loaded is False

    def test_get_model_not_loaded(self):
        from server.tts_engine import TTSEngine
        engine = TTSEngine()
        with pytest.raises(RuntimeError, match="not loaded"):
            engine.get_model("voice_design")

    def test_get_health_no_gpu(self):
        from unittest.mock import patch
        from server.tts_engine import TTSEngine
        engine = TTSEngine()
        # Mock torch import to avoid access violation on Windows without proper CUDA
        with patch.dict("sys.modules", {"torch": None}):
            health = engine.get_health()
        assert health["status"] == "loading"
        assert health["loaded_models"] == []
