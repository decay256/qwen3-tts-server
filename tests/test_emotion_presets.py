"""Tests for emotion presets and casting batch builder."""

import pytest
from server.emotion_presets import (
    EMOTION_PRESETS,
    EMOTION_ORDER,
    EmotionPreset,
    build_casting_batch,
)


def test_all_emotions_in_order():
    """Every emotion in EMOTION_ORDER exists in EMOTION_PRESETS."""
    for name in EMOTION_ORDER:
        assert name in EMOTION_PRESETS, f"Missing preset: {name}"


def test_preset_structure():
    """Each preset has required fields."""
    for name, preset in EMOTION_PRESETS.items():
        assert preset.name == name
        assert len(preset.instruct) > 5
        assert len(preset.ref_text) > 10
        assert len(preset.tags) >= 1
        # At least one tag should relate to the emotion name
        assert any(name.startswith(t) or t.startswith(name) for t in preset.tags), \
            f"No tag matching '{name}' in {preset.tags}"


def test_get_instruct():
    preset = EMOTION_PRESETS["angry"]
    result = preset.get_instruct("Deep male voice")
    assert result.startswith("Deep male voice, ")
    assert "furious" in result or "rage" in result or "anger" in result


def test_build_casting_batch_all_emotions():
    items = build_casting_batch("maya", "Young woman, warm voice")
    assert len(items) == len(EMOTION_ORDER)
    
    names = [i["name"] for i in items]
    assert "maya_neutral" in names
    assert "maya_angry" in names
    assert "maya_laughing" in names

    # Check structure
    for item in items:
        assert item["name"].startswith("maya_")
        assert "text" in item
        assert "instruct" in item
        assert "Young woman, warm voice" in item["instruct"]
        assert "tags" in item


def test_build_casting_batch_subset():
    items = build_casting_batch("chen", "Male voice", emotions=["neutral", "angry"])
    assert len(items) == 2
    assert items[0]["name"] == "chen_neutral"
    assert items[1]["name"] == "chen_angry"


def test_build_casting_batch_text_override():
    items = build_casting_batch(
        "maya", "Female voice",
        emotions=["happy"],
        text_overrides={"happy": "Custom happy text here!"},
    )
    assert len(items) == 1
    assert items[0]["text"] == "Custom happy text here!"


def test_build_casting_batch_unknown_emotion_skipped():
    items = build_casting_batch("x", "Voice", emotions=["neutral", "nonexistent"])
    assert len(items) == 1  # nonexistent is silently skipped


def test_ref_texts_are_reasonably_long():
    """Ref texts should be 15-50 words for ~5-15s of speech."""
    for name, preset in EMOTION_PRESETS.items():
        words = len(preset.ref_text.split())
        assert 8 <= words <= 60, f"{name} ref_text has {words} words"
