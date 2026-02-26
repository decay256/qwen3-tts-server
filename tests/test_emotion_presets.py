"""Tests for emotion presets, mode presets, and casting batch builder."""

import pytest
from server.emotion_presets import (
    EMOTION_PRESETS,
    EMOTION_ORDER,
    EMOTION_INTENSITIES,
    MODE_PRESETS,
    MODE_ORDER,
    EmotionPreset,
    ModePreset,
    build_casting_batch,
)


# ── Emotion preset tests ───────────────────────────────────────────

def test_all_emotions_in_order():
    for name in EMOTION_ORDER:
        assert name in EMOTION_PRESETS


def test_emotion_count():
    assert len(EMOTION_PRESETS) == 9
    assert "neutral" not in EMOTION_PRESETS  # neutral is the base voice


def test_emotion_preset_structure():
    for name, preset in EMOTION_PRESETS.items():
        assert preset.name == name
        for intensity in EMOTION_INTENSITIES:
            instruct = getattr(preset, f"instruct_{intensity}")
            ref_text = getattr(preset, f"ref_text_{intensity}")
            assert len(instruct) > 5, f"{name}.instruct_{intensity} too short"
            assert len(ref_text) > 10, f"{name}.ref_text_{intensity} too short"
        assert len(preset.tags) >= 1


def test_emotion_get_instruct_with_intensity():
    preset = EMOTION_PRESETS["angry"]
    med = preset.get_instruct("Male voice", "medium")
    intense = preset.get_instruct("Male voice", "intense")
    assert "Male voice" in med
    assert "Male voice" in intense
    assert med != intense


def test_emotion_get_ref_text_by_intensity():
    preset = EMOTION_PRESETS["happy"]
    assert preset.get_ref_text("medium") != preset.get_ref_text("intense")


def test_emotion_intensities():
    assert EMOTION_INTENSITIES == ["medium", "intense"]


# ── Mode preset tests ──────────────────────────────────────────────

def test_all_modes_in_order():
    for name in MODE_ORDER:
        assert name in MODE_PRESETS


def test_mode_count():
    assert len(MODE_PRESETS) == 13


def test_mode_preset_structure():
    for name, preset in MODE_PRESETS.items():
        assert preset.name == name
        assert len(preset.instruct) > 5, f"{name}.instruct too short"
        assert len(preset.ref_text) > 10, f"{name}.ref_text too short"
        assert len(preset.tags) >= 1


def test_mode_get_instruct():
    preset = MODE_PRESETS["screaming"]
    result = preset.get_instruct("Female voice")
    assert "Female voice" in result
    assert "SCREAM" in result.upper()


# ── Casting batch builder tests ────────────────────────────────────

def test_build_casting_batch_all():
    items = build_casting_batch("maya", "Young woman, mid pitch")
    # 9 emotions × 2 intensities + 15 modes = 33
    expected = len(EMOTION_ORDER) * len(EMOTION_INTENSITIES) + len(MODE_ORDER)
    assert len(items) == expected


def test_build_casting_batch_emotions_only():
    items = build_casting_batch("maya", "Voice", modes=[])
    assert len(items) == len(EMOTION_ORDER) * len(EMOTION_INTENSITIES)


def test_build_casting_batch_modes_only():
    items = build_casting_batch("maya", "Voice", emotions=[])
    assert len(items) == len(MODE_ORDER)


def test_build_casting_batch_subset_emotions():
    items = build_casting_batch("chen", "Male voice", emotions=["angry", "happy"], modes=[])
    assert len(items) == 2 * 2  # 2 emotions × 2 intensities


def test_build_casting_batch_subset_intensities():
    items = build_casting_batch("chen", "Male voice", intensities=["intense"], modes=[])
    assert len(items) == len(EMOTION_ORDER)


def test_build_casting_batch_text_override():
    items = build_casting_batch(
        "maya", "Female voice",
        emotions=["happy"], intensities=["medium"], modes=[],
        text_overrides={"happy_medium": "Custom happy text!"},
    )
    assert len(items) == 1
    assert items[0]["text"] == "Custom happy text!"


def test_build_casting_batch_mode_text_override():
    items = build_casting_batch(
        "maya", "Female voice",
        emotions=[], modes=["screaming"],
        text_overrides={"screaming": "CUSTOM SCREAM TEXT!"},
    )
    assert len(items) == 1
    assert items[0]["text"] == "CUSTOM SCREAM TEXT!"


def test_build_casting_batch_tags_include_intensity():
    items = build_casting_batch("x", "Voice", emotions=["angry"], intensities=["intense"], modes=[])
    assert "intense" in items[0]["tags"]
    assert "angry" in items[0]["tags"]


def test_build_casting_batch_mode_tags():
    items = build_casting_batch("x", "Voice", emotions=[], modes=["radio"])
    assert "radio" in items[0]["tags"]


def test_ref_texts_reasonable_length():
    for name, preset in EMOTION_PRESETS.items():
        for intensity in EMOTION_INTENSITIES:
            text = preset.get_ref_text(intensity)
            words = len(text.split())
            assert 5 <= words <= 60, f"{name}_{intensity} ref_text has {words} words"
    for name, preset in MODE_PRESETS.items():
        words = len(preset.ref_text.split())
        assert 5 <= words <= 60, f"mode {name} ref_text has {words} words"


def test_no_neutral_in_emotions():
    """Neutral is the base voice — no need for a separate emotion preset."""
    assert "neutral" not in EMOTION_PRESETS
    assert "neutral" not in EMOTION_ORDER


def test_build_casting_batch_voice_library_metadata():
    """Casting batch items include voice library metadata."""
    from server.emotion_presets import build_casting_batch
    items = build_casting_batch("kira", "Adult woman, husky voice", emotions=["happy"], modes=[])
    assert len(items) == 2  # happy medium + happy intense
    for item in items:
        assert item["character"] == "kira"
        assert item["emotion"] == "happy"
        assert item["base_description"] == "Adult woman, husky voice"
        assert "description" in item
    assert items[0]["intensity"] == "medium"
    assert items[1]["intensity"] == "intense"


def test_build_casting_batch_mode_metadata():
    """Mode items include voice library metadata."""
    from server.emotion_presets import build_casting_batch
    items = build_casting_batch("kira", "Adult woman", emotions=[], modes=["laughing"])
    assert len(items) == 1
    assert items[0]["character"] == "kira"
    assert items[0]["emotion"] == "laughing"
    assert items[0]["intensity"] == "full"
    assert "mode" in items[0]["description"]
