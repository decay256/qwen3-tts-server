"""Standard emotion presets for voice casting.

Each emotion has a default reference text that naturally expresses that emotion,
plus an instruct modifier that gets appended to the base voice description.

Usage:
    base_desc = "Young woman, warm alto voice"
    emotion = EMOTION_PRESETS["angry"]
    full_instruct = f"{base_desc}, {emotion['instruct']}"
    text = emotion["ref_text"]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class EmotionPreset:
    """A standard emotion preset for voice casting."""
    name: str
    instruct: str  # Appended to base voice description
    ref_text: str  # Default reference text expressing this emotion
    tags: list[str]  # Auto-tags for prompt filtering

    def get_instruct(self, base_description: str) -> str:
        """Combine base voice description with emotion instruct."""
        return f"{base_description}, {self.instruct}"


# Reference texts are designed to:
# 1. Naturally express the emotion through content and punctuation
# 2. Be 5-15 seconds when spoken (~15-40 words)
# 3. Be generic enough for any character
# 4. Include emotion-triggering punctuation and onomatopoeia

EMOTION_PRESETS: dict[str, EmotionPreset] = {
    "neutral": EmotionPreset(
        name="neutral",
        instruct="speaking calmly and clearly, measured pace",
        ref_text="The results came back this morning. Everything looks normal, nothing out of the ordinary. We can proceed as planned.",
        tags=["neutral", "calm"],
    ),
    "happy": EmotionPreset(
        name="happy",
        instruct="genuinely happy, warm smile in the voice, upbeat",
        ref_text="Oh my god, it actually worked! I'm so happy right now, this is the best news I've had all year!",
        tags=["happy", "joy"],
    ),
    "excited": EmotionPreset(
        name="excited",
        instruct="bursting with excitement, speaking fast, barely containing energy",
        ref_text="Yes! YES! We did it! I can't believe it, this changes everything! Come on, we have to tell the others right now!",
        tags=["excited", "energetic"],
    ),
    "sad": EmotionPreset(
        name="sad",
        instruct="deep sadness, voice heavy with grief, slow and quiet",
        ref_text="I waited so long... and now it's just... gone. All of it. I don't even know what to say anymore.",
        tags=["sad", "grief"],
    ),
    "angry": EmotionPreset(
        name="angry",
        instruct="furious, controlled rage, clipped words, barely containing anger",
        ref_text="No. Absolutely not. You had one job, one simple task, and you couldn't even manage that. This is completely unacceptable.",
        tags=["angry", "furious"],
    ),
    "fearful": EmotionPreset(
        name="fearful",
        instruct="terrified, voice shaking, speaking quickly with rising panic",
        ref_text="Something's wrong. Something's very, very wrong. We need to get out of here, right now. Please, we have to go!",
        tags=["fearful", "scared", "panic"],
    ),
    "tender": EmotionPreset(
        name="tender",
        instruct="gentle, soft, full of warmth and affection, intimate",
        ref_text="Hey... it's okay. I'm right here. You don't have to be strong all the time. I've got you.",
        tags=["tender", "loving", "gentle"],
    ),
    "whispering": EmotionPreset(
        name="whispering",
        instruct="hushed whisper, barely audible, conspiratorial",
        ref_text="Shh... listen. Do you hear that? Don't move. Don't make a sound. Just stay perfectly still.",
        tags=["whisper", "quiet"],
    ),
    "shouting": EmotionPreset(
        name="shouting",
        instruct="shouting loudly, projecting voice, urgent and commanding",
        ref_text="GET DOWN! Everybody get down NOW! Move, move, move! Get to the other side, GO!",
        tags=["shouting", "loud", "commanding"],
    ),
    "laughing": EmotionPreset(
        name="laughing",
        instruct="laughing while speaking, can barely get the words out, infectious amusement",
        ref_text="Hahaha! Oh no, oh no... haha, I can't... did you see their face? That was the funniest thing I have ever seen!",
        tags=["laughing", "amused"],
    ),
    "sarcastic": EmotionPreset(
        name="sarcastic",
        instruct="dripping with sarcasm, dry wit, slightly mocking tone",
        ref_text="Oh, brilliant. What a fantastic idea. I can't imagine how anything could possibly go wrong with that plan. Truly inspired.",
        tags=["sarcastic", "ironic"],
    ),
    "nervous": EmotionPreset(
        name="nervous",
        instruct="anxious, fidgety, voice slightly unsteady, hesitant",
        ref_text="I... okay, um, so here's the thing. I don't know exactly how to say this, but... there might be a small problem. Maybe.",
        tags=["nervous", "anxious"],
    ),
}

# Ordered list for consistent batch generation
EMOTION_ORDER = [
    "neutral", "happy", "excited", "sad", "angry",
    "fearful", "tender", "whispering", "shouting",
    "laughing", "sarcastic", "nervous",
]


def build_casting_batch(
    character_name: str,
    base_description: str,
    emotions: list[str] | None = None,
    text_overrides: dict[str, str] | None = None,
) -> list[dict]:
    """Build a batch design request for voice casting.

    Args:
        character_name: Character name (used in prompt naming, e.g. "maya").
        base_description: Base voice description (e.g. "Young woman, warm alto voice").
        emotions: Which emotions to generate. Defaults to all.
        text_overrides: Override default ref_text for specific emotions.

    Returns:
        List of items suitable for POST /api/v1/voices/design/batch
    """
    emotions = emotions or EMOTION_ORDER
    text_overrides = text_overrides or {}
    items = []

    for emotion_name in emotions:
        preset = EMOTION_PRESETS.get(emotion_name)
        if not preset:
            continue

        text = text_overrides.get(emotion_name, preset.ref_text)
        instruct = preset.get_instruct(base_description)

        items.append({
            "name": f"{character_name}_{emotion_name}",
            "text": text,
            "instruct": instruct,
            "language": "English",
            "tags": [emotion_name] + preset.tags,
        })

    return items
