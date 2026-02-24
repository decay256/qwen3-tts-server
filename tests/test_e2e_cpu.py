"""End-to-end CPU integration tests for TTS synthesis.

Tests actual model loading and audio generation in bfloat16 on CPU.
These tests are slow (~2-3 min each) but verify the full pipeline works.
Mark with @pytest.mark.slow so they can be skipped in fast CI runs.

Run with: pytest tests/test_e2e_cpu.py -v --timeout=300
Skip in CI: pytest tests/ --timeout=10 -m "not slow"
"""

import os
import json
import base64
import tempfile
import time

import numpy as np
import pytest

# Force CPU mode
os.environ["CUDA_DEVICE"] = "cpu"
if "ENABLED_MODELS" not in os.environ:
    os.environ["ENABLED_MODELS"] = "voice_design"


@pytest.fixture(scope="module")
def engine():
    """Load TTS engine once for all tests in this module (slow)."""
    from server.tts_engine import TTSEngine
    
    e = TTSEngine()
    print("Loading voice_design model on CPU (bf16)...")
    t0 = time.time()
    e.load_models()
    print(f"Model loaded in {time.time() - t0:.1f}s")
    return e


@pytest.mark.slow
class TestVoiceDesignCPU:
    """Test voice design synthesis on CPU."""

    def test_engine_loaded(self, engine):
        """Engine loads successfully in CPU bf16 mode."""
        assert engine.is_loaded
        health = engine.get_health()
        assert "voice_design" in health.get("loaded_models", [])

    def test_minimal_synthesis(self, engine):
        """Generate shortest possible audio to verify pipeline."""
        t0 = time.time()
        wav, sr = engine.generate_voice_design(
            text="Hi.",
            description="Young woman, warm voice",
            language="English",
        )
        elapsed = time.time() - t0
        print(f"Synthesis took {elapsed:.1f}s, {len(wav)} samples, sr={sr}")

        assert sr == 24000
        assert len(wav) > 0
        assert wav.dtype == np.float32 or wav.dtype == np.float64
        # Should produce at least some audio (>0.1s)
        assert len(wav) / sr > 0.1

    def test_short_sentence(self, engine):
        """Generate a short sentence — tests text processing."""
        wav, sr = engine.generate_voice_design(
            text="The sky is blue.",
            description="Deep male narrator voice",
            language="English",
        )
        assert sr == 24000
        assert len(wav) / sr > 0.3  # At least 0.3s of audio

    def test_wav_format_conversion(self, engine):
        """Test WAV encoding from raw samples."""
        from server.tts_engine import wav_to_format

        wav, sr = engine.generate_voice_design(
            text="Test.",
            description="Female voice",
            language="English",
        )
        
        # Convert to WAV bytes
        wav_bytes = wav_to_format(wav, sr, "wav")
        assert len(wav_bytes) > 44  # WAV header is 44 bytes
        assert wav_bytes[:4] == b"RIFF"

    def test_different_descriptions_produce_different_audio(self, engine):
        """Voice design should produce different output for different descriptions."""
        wav1, _ = engine.generate_voice_design(
            text="Hello.",
            description="Deep old male voice, gravelly",
            language="English",
        )
        wav2, _ = engine.generate_voice_design(
            text="Hello.",
            description="High-pitched young female voice, bright",
            language="English",
        )
        # Audio should differ (not identical)
        min_len = min(len(wav1), len(wav2))
        if min_len > 0:
            assert not np.array_equal(wav1[:min_len], wav2[:min_len])


@pytest.mark.slow
class TestVoiceCloneCPU:
    """Test voice cloning on CPU — requires 'base' model.
    
    Only runs if base model is enabled. On 8GB RAM, only one model
    fits at a time, so these tests may be skipped.
    """

    @pytest.fixture(scope="class")
    def clone_engine(self):
        """Load base model for clone tests."""
        if "base" not in os.environ.get("ENABLED_MODELS", ""):
            pytest.skip("base model not enabled (set ENABLED_MODELS=base)")
        
        from server.tts_engine import TTSEngine
        os.environ["ENABLED_MODELS"] = "base"
        
        e = TTSEngine()
        e.load_models()
        return e

    def test_clone_with_ref_audio(self, clone_engine):
        """Clone from a reference audio file."""
        # Create a minimal reference WAV (1 second of silence — not ideal
        # but tests the pipeline without needing a real recording)
        ref_wav = np.zeros(24000, dtype=np.float32)
        ref_wav[::100] = 0.1  # Add tiny clicks so it's not pure silence

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            import soundfile as sf
            sf.write(f.name, ref_wav, 24000)
            ref_path = f.name

        try:
            with open(ref_path, "rb") as f:
                ref_b64 = base64.b64encode(f.read()).decode()

            wav, sr = clone_engine.generate_voice_clone(
                text="Hi.",
                ref_audio_b64=ref_b64,
                ref_text="Testing one two three.",  # ref_text is REQUIRED by qwen-tts
                language="English",
            )
            assert sr == 24000
            assert len(wav) > 0
        finally:
            os.unlink(ref_path)
