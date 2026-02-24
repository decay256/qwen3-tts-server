"""Formant normalization for voice timbre consistency.

When VoiceDesign generates different emotion variants of "the same" voice,
the timbre (formant structure) can drift. This module normalizes the formants
of a target clip toward a reference clip while preserving the emotional
delivery (pitch contour, speaking rate, vocal quality).

Uses praat-parselmouth for formant extraction and manipulation.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import parselmouth
from parselmouth.praat import call

logger = logging.getLogger(__name__)


@dataclass
class FormantStats:
    """Mean formant frequencies extracted from a voice clip."""
    f1: float  # First formant (jaw openness, ~500-800 Hz)
    f2: float  # Second formant (tongue position, ~1000-2500 Hz)
    f3: float  # Third formant (lip rounding, ~2500-3500 Hz)
    f4: float  # Fourth formant (vocal tract length, ~3500-4500 Hz)

    def shift_ratios(self, target: FormantStats) -> tuple[float, float, float, float]:
        """Calculate ratios to shift self toward target."""
        def safe_ratio(ref: float, tgt: float) -> float:
            if tgt < 1.0 or ref < 1.0:
                return 1.0
            return ref / tgt
        return (
            safe_ratio(self.f1, target.f1),
            safe_ratio(self.f2, target.f2),
            safe_ratio(self.f3, target.f3),
            safe_ratio(self.f4, target.f4),
        )


def extract_formants(
    audio: np.ndarray,
    sr: int,
    max_formant: float = 5500.0,
    num_formants: int = 5,
) -> FormantStats:
    """Extract mean formant frequencies from audio.

    Args:
        audio: Audio samples (float, mono).
        sr: Sample rate.
        max_formant: Maximum formant frequency (5500 for female, 5000 for male).
        num_formants: Number of formants to track.

    Returns:
        FormantStats with mean F1-F4 values.
    """
    snd = parselmouth.Sound(audio, sampling_frequency=sr)
    formant = call(snd, "To Formant (burg)", 0.0, num_formants, max_formant, 0.025, 50.0)

    # Extract mean formant values, ignoring unvoiced frames
    means = []
    for i in range(1, 5):  # F1-F4
        values = []
        n_frames = call(formant, "Get number of frames")
        for frame in range(1, n_frames + 1):
            val = call(formant, "Get value at time", i, call(formant, "Get time from frame number", frame), "hertz", "Linear")
            if val == val and val > 0:  # not NaN and positive
                values.append(val)
        means.append(np.mean(values) if values else 0.0)

    return FormantStats(f1=means[0], f2=means[1], f3=means[2], f4=means[3])


def normalize_formants(
    target_audio: np.ndarray,
    target_sr: int,
    reference_audio: np.ndarray,
    reference_sr: int,
    strength: float = 0.7,
    max_formant_ref: float = 5500.0,
    max_formant_target: float = 5500.0,
    preserve_pitch: bool = True,
) -> tuple[np.ndarray, int]:
    """Normalize target audio formants toward reference audio.

    Shifts the spectral envelope of the target to match the reference's
    formant structure while preserving the target's pitch contour, speaking
    rate, and overall vocal quality.

    Args:
        target_audio: Audio to normalize (float, mono).
        target_sr: Target sample rate.
        reference_audio: Reference audio for formant targets.
        reference_sr: Reference sample rate.
        strength: How aggressively to shift (0.0 = no change, 1.0 = full shift).
        max_formant_ref: Max formant Hz for reference (5500 female, 5000 male).
        max_formant_target: Max formant Hz for target.
        preserve_pitch: If True, restore original pitch contour after formant shift.

    Returns:
        (normalized_audio, sample_rate) tuple.
    """
    # Extract formants from both
    ref_formants = extract_formants(reference_audio, reference_sr, max_formant_ref)
    tgt_formants = extract_formants(target_audio, target_sr, max_formant_target)

    logger.info(
        "Formants — ref: F1=%.0f F2=%.0f F3=%.0f F4=%.0f | target: F1=%.0f F2=%.0f F3=%.0f F4=%.0f",
        ref_formants.f1, ref_formants.f2, ref_formants.f3, ref_formants.f4,
        tgt_formants.f1, tgt_formants.f2, tgt_formants.f3, tgt_formants.f4,
    )

    # Calculate shift ratios
    r1, r2, r3, r4 = ref_formants.shift_ratios(tgt_formants)

    # Apply strength (blend toward 1.0 = no change)
    r1 = 1.0 + (r1 - 1.0) * strength
    r2 = 1.0 + (r2 - 1.0) * strength
    r3 = 1.0 + (r3 - 1.0) * strength
    r4 = 1.0 + (r4 - 1.0) * strength

    logger.info("Shift ratios (strength=%.1f): F1=%.3f F2=%.3f F3=%.3f F4=%.3f", strength, r1, r2, r3, r4)

    # Apply formant shifting via Praat
    snd = parselmouth.Sound(target_audio, sampling_frequency=target_sr)

    if preserve_pitch:
        # Extract original pitch
        pitch = call(snd, "To Pitch", 0.0, 75.0, 600.0)

    # Use Change Gender to shift formants
    # The "formant shift ratio" parameter shifts all formants proportionally
    # We use the geometric mean of F1-F4 ratios as the overall shift
    overall_ratio = (r1 * r2 * r3 * r4) ** 0.25

    # Clamp to reasonable range
    overall_ratio = max(0.8, min(1.2, overall_ratio))

    if abs(overall_ratio - 1.0) < 0.01:
        logger.info("Formants already close enough (ratio=%.3f), skipping normalization", overall_ratio)
        return target_audio, target_sr

    # Apply formant shift using Change Gender
    # Parameters: minimum_pitch, maximum_pitch, formant_shift_ratio, new_pitch_median, pitch_range_factor, duration_factor
    shifted = call(
        snd, "Change gender",
        75.0,  # min pitch
        600.0,  # max pitch
        overall_ratio,  # formant shift ratio
        0.0,  # new pitch median (0 = keep original)
        1.0,  # pitch range factor (1 = keep)
        1.0,  # duration factor (1 = keep)
    )

    result = shifted.values[0].astype(np.float32)
    return result, int(shifted.sampling_frequency)


def normalize_audio_bytes(
    target_bytes: bytes,
    reference_bytes: bytes,
    strength: float = 0.7,
) -> tuple[bytes, int]:
    """Normalize formants of target WAV bytes toward reference WAV bytes.

    Convenience wrapper that handles WAV encoding/decoding.

    Args:
        target_bytes: WAV file bytes to normalize.
        reference_bytes: WAV file bytes for reference formants.
        strength: Normalization strength (0.0-1.0).

    Returns:
        (wav_bytes, sample_rate) tuple.
    """
    import soundfile as sf

    target_audio, target_sr = sf.read(io.BytesIO(target_bytes))
    reference_audio, reference_sr = sf.read(io.BytesIO(reference_bytes))

    # Convert to mono if needed
    if target_audio.ndim > 1:
        target_audio = target_audio.mean(axis=1)
    if reference_audio.ndim > 1:
        reference_audio = reference_audio.mean(axis=1)

    result, result_sr = normalize_formants(
        target_audio.astype(np.float32), target_sr,
        reference_audio.astype(np.float32), reference_sr,
        strength=strength,
    )

    buf = io.BytesIO()
    sf.write(buf, result, result_sr, format="WAV")
    return buf.getvalue(), result_sr
