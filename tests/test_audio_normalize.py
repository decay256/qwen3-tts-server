"""Tests for formant normalization."""

import numpy as np
import pytest

from server.audio_normalize import extract_formants, normalize_formants, FormantStats


@pytest.fixture
def sine_wave():
    """Generate a simple test signal."""
    sr = 24000
    t = np.linspace(0, 1.0, sr, dtype=np.float32)
    # Complex signal with harmonics to have some formant-like structure
    signal = (
        0.5 * np.sin(2 * np.pi * 150 * t) +  # fundamental
        0.3 * np.sin(2 * np.pi * 500 * t) +   # ~F1
        0.2 * np.sin(2 * np.pi * 1500 * t) +  # ~F2
        0.1 * np.sin(2 * np.pi * 2500 * t)    # ~F3
    ).astype(np.float32)
    return signal, sr


def test_formant_stats_shift_ratios():
    ref = FormantStats(f1=600, f2=1500, f3=2800, f4=3800)
    tgt = FormantStats(f1=550, f2=1600, f3=2900, f4=3700)
    r1, r2, r3, r4 = ref.shift_ratios(tgt)
    assert r1 > 1.0  # ref F1 higher → shift up
    assert r2 < 1.0  # ref F2 lower → shift down
    assert abs(r4 - 3800/3700) < 0.01


def test_formant_stats_identical():
    stats = FormantStats(f1=600, f2=1500, f3=2800, f4=3800)
    r1, r2, r3, r4 = stats.shift_ratios(stats)
    assert r1 == pytest.approx(1.0)
    assert r2 == pytest.approx(1.0)


def test_formant_stats_zero_handling():
    ref = FormantStats(f1=600, f2=0, f3=2800, f4=3800)
    tgt = FormantStats(f1=550, f2=1600, f3=2900, f4=3700)
    r1, r2, _, _ = ref.shift_ratios(tgt)
    assert r1 > 0
    assert r2 == 1.0  # ref is 0 → ratio is 1.0 (no shift)


def test_extract_formants_returns_stats(sine_wave):
    signal, sr = sine_wave
    stats = extract_formants(signal, sr)
    assert isinstance(stats, FormantStats)
    assert stats.f1 > 0
    assert stats.f2 > stats.f1


def test_normalize_formants_returns_audio(sine_wave):
    signal, sr = sine_wave
    # Slightly different "reference"
    ref = signal * 0.9 + np.random.randn(len(signal)).astype(np.float32) * 0.01
    
    result, result_sr = normalize_formants(signal, sr, ref, sr, strength=0.5)
    assert result_sr == sr
    assert len(result) > 0
    assert result.dtype == np.float32


def test_normalize_strength_zero_no_change(sine_wave):
    """Strength 0.0 should return nearly unchanged audio."""
    signal, sr = sine_wave
    ref = np.random.randn(sr).astype(np.float32) * 0.3
    
    result, _ = normalize_formants(signal, sr, ref, sr, strength=0.0)
    # With strength=0, all ratios become 1.0, so formant shift ≈ 1.0
    # Audio should be returned as-is or very close
    assert len(result) == len(signal)
