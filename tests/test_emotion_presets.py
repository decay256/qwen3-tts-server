"""Tests for emotion presets and casting batch builder."""

import pytest
from server.emotion_presets import (
    EMOTION_PRESETS,
    EMOTION_ORDER,
    INTENSITIES,
    EmotionPreset,
    build_casting_batch,
)


def test_all_emotions_in_order():
    for name in EMOTION_ORDER:
        assert name in EMOTION_PRESETS


def test_preset_structure():
    for name, preset in EMOTION_PRESETS.items():
        assert preset.name == name
        for intensity in INTENSITIES:
            instruct = getattr(preset, f"instruct_{intensity}")
            ref_text = getattr(preset, f"ref_text_{intensity}")
            assert len(instruct) > 5, f"{name}.instruct_{intensity} too short"
            assert len(ref_text) > 10, f"{name}.ref_text_{intensity} too short"
        assert len(preset.tags) >= 1


def test_get_instruct_with_intensity():
    preset = EMOTION_PRESETS["angry"]
    light = preset.get_instruct("Male voice", "light")
    full = preset.get_instruct("Male voice", "full")
    assert "Male voice" in light
    assert "Male voice" in full
    assert light != full  # different intensities produce different instructs


def test_get_ref_text_by_intensity():
    preset = EMOTION_PRESETS["happy"]
    assert preset.get_ref_text("light") != preset.get_ref_text("full")


def test_build_casting_batch_all():
    items = build_casting_batch("maya", "Young woman, warm voice")
    # 12 emotions × 3 intensities = 36
    assert len(items) == len(EMOTION_ORDER) * len(INTENSITIES)
    names = [i["name"] for i in items]
    assert "maya_neutral_light" in names
    assert "maya_angry_full" in names
    assert "maya_laughing_medium" in names


def test_build_casting_batch_subset_emotions():
    items = build_casting_batch("chen", "Male voice", emotions=["neutral", "angry"])
    assert len(items) == 2 * 3  # 2 emotions × 3 intensities


def test_build_casting_batch_subset_intensities():
    items = build_casting_batch("chen", "Male voice", intensities=["medium"])
    assert len(items) == len(EMOTION_ORDER)  # all emotions, 1 intensity each


def test_build_casting_batch_text_override():
    items = build_casting_batch(
        "maya", "Female voice",
        emotions=["happy"],
        intensities=["medium"],
        text_overrides={"happy_medium": "Custom happy text!"},
    )
    assert len(items) == 1
    assert items[0]["text"] == "Custom happy text!"


def test_build_casting_batch_tags_include_intensity():
    items = build_casting_batch("x", "Voice", emotions=["angry"], intensities=["full"])
    assert "full" in items[0]["tags"]
    assert "angry" in items[0]["tags"]


def test_ref_texts_reasonable_length():
    for name, preset in EMOTION_PRESETS.items():
        for intensity in INTENSITIES:
            text = preset.get_ref_text(intensity)
            words = len(text.split())
            assert 5 <= words <= 60, f"{name}_{intensity} ref_text has {words} words"
