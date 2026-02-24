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
    instruct_light: str    # Subtle/restrained version
    instruct_medium: str   # Standard expression
    instruct_full: str     # Maximum intensity
    ref_text_light: str    # Text for light intensity
    ref_text_medium: str   # Text for medium intensity
    ref_text_full: str     # Text for full intensity
    tags: list[str]

    def get_instruct(self, base_description: str, intensity: str = "medium") -> str:
        """Combine base voice description with emotion instruct at given intensity."""
        instruct = getattr(self, f"instruct_{intensity}", self.instruct_medium)
        return f"{base_description}, {instruct}"

    def get_ref_text(self, intensity: str = "medium") -> str:
        """Get reference text for given intensity."""
        return getattr(self, f"ref_text_{intensity}", self.ref_text_medium)


INTENSITIES = ["light", "medium", "full"]


# Reference texts are designed to:
# 1. Naturally express the emotion at the specified intensity
# 2. Be 5-15 seconds when spoken (~15-40 words)
# 3. Be generic enough for any character
# 4. Light = subtle hint, Medium = clear expression, Full = extreme/overwhelming

EMOTION_PRESETS: dict[str, EmotionPreset] = {
    "neutral": EmotionPreset(
        name="neutral",
        instruct_light="speaking quietly and calmly, relaxed",
        instruct_medium="speaking calmly and clearly, measured pace",
        instruct_full="speaking with deliberate precision, authoritative and composed",
        ref_text_light="Yeah, that seems about right. Nothing unusual there.",
        ref_text_medium="The results came back this morning. Everything looks normal, nothing out of the ordinary. We can proceed as planned.",
        ref_text_full="Let me be perfectly clear about the situation. The data is consistent across all measurements, every parameter within expected bounds, no anomalies whatsoever.",
        tags=["neutral", "calm"],
    ),
    "happy": EmotionPreset(
        name="happy",
        instruct_light="slight warmth in the voice, quietly pleased",
        instruct_medium="genuinely happy, warm smile in the voice, upbeat",
        instruct_full="overjoyed, voice breaking with happiness, ecstatic",
        ref_text_light="Oh, that's nice. I'm really glad to hear that, honestly.",
        ref_text_medium="Oh my god, it actually worked! I'm so happy right now, this is the best news I've had all year!",
        ref_text_full="I can't... I just can't believe it! This is the happiest day of my entire life! I'm going to cry, I'm so happy right now!",
        tags=["happy", "joy"],
    ),
    "excited": EmotionPreset(
        name="excited",
        instruct_light="slightly energized, a spark of enthusiasm",
        instruct_medium="excited, speaking faster, building energy",
        instruct_full="bursting with excitement, speaking fast, barely containing energy, almost manic",
        ref_text_light="Oh, interesting! I think we might be onto something here.",
        ref_text_medium="This is incredible, do you realize what this means? We have to look into this right now!",
        ref_text_full="Yes! YES! We did it! I can't believe it, this changes EVERYTHING! Come on, come on, we have to tell the others right now!",
        tags=["excited", "energetic"],
    ),
    "sad": EmotionPreset(
        name="sad",
        instruct_light="slightly melancholic, a hint of wistfulness in the voice",
        instruct_medium="sad, voice heavy with disappointment, slow and quiet",
        instruct_full="deep grief, voice breaking, barely holding back tears",
        ref_text_light="I suppose that's just how it goes sometimes. It's a shame, really.",
        ref_text_medium="I waited so long... and now it's just... gone. All of it. I don't even know what to say anymore.",
        ref_text_full="They're gone. They're really gone and they're never coming back. I can't... I can't do this. I don't know how to keep going.",
        tags=["sad", "grief"],
    ),
    "angry": EmotionPreset(
        name="angry",
        instruct_light="slightly irritated, controlled displeasure, terse",
        instruct_medium="angry, clipped words, barely containing frustration",
        instruct_full="furious, seething with rage, explosive, voice shaking with anger",
        ref_text_light="That's... not ideal. I really wish you had told me about this sooner.",
        ref_text_medium="No. Absolutely not. You had one job, one simple task, and you couldn't even manage that. This is unacceptable.",
        ref_text_full="How DARE you! After everything I did for you, after everything I sacrificed, THIS is what I get?! Get out. GET OUT!",
        tags=["angry", "furious"],
    ),
    "fearful": EmotionPreset(
        name="fearful",
        instruct_light="slightly uneasy, a hint of worry creeping in",
        instruct_medium="scared, voice shaking slightly, growing anxiety",
        instruct_full="terrified, voice shaking with panic, hyperventilating, desperate",
        ref_text_light="I'm not sure about this. Something doesn't feel quite right.",
        ref_text_medium="Something's wrong. Something's very wrong. We need to get out of here, right now. Please.",
        ref_text_full="Oh god, oh god, oh god... no no no! We're trapped, we're completely trapped! Someone help us, PLEASE! I can't breathe!",
        tags=["fearful", "scared", "panic"],
    ),
    "tender": EmotionPreset(
        name="tender",
        instruct_light="gentle, a touch of warmth and care",
        instruct_medium="soft, full of warmth and affection, caring",
        instruct_full="deeply intimate, voice barely above a whisper, overflowing with love",
        ref_text_light="Don't worry about it, okay? It's going to be fine.",
        ref_text_medium="Hey... it's okay. I'm right here. You don't have to be strong all the time. I've got you.",
        ref_text_full="I love you. I love you so much it hurts. You are the most important thing in my world, and I need you to know that. Always.",
        tags=["tender", "loving", "gentle"],
    ),
    "whispering": EmotionPreset(
        name="whispering",
        instruct_light="speaking quietly, lowered voice",
        instruct_medium="hushed whisper, barely audible, conspiratorial",
        instruct_full="barely breathing the words, extreme whisper, terrified of being heard",
        ref_text_light="Keep your voice down. We don't want anyone else hearing this.",
        ref_text_medium="Shh... listen. Do you hear that? Don't move. Don't make a sound. Just stay perfectly still.",
        ref_text_full="Don't... breathe... it's right outside the door... if it hears us... just close your eyes and don't move a muscle...",
        tags=["whisper", "quiet"],
    ),
    "shouting": EmotionPreset(
        name="shouting",
        instruct_light="raised voice, firm and assertive",
        instruct_medium="shouting, projecting voice, urgent and commanding",
        instruct_full="screaming at the top of lungs, desperate, raw vocal power",
        ref_text_light="Hey! Over here! Can you hear me? We need to talk about this!",
        ref_text_medium="GET DOWN! Everybody get down NOW! Move, move, move! Get to the other side, GO!",
        ref_text_full="NOOOOO! STOP! SOMEBODY STOP THEM! FOR GOD'S SAKE, HELP! HELP US! PLEASE!",
        tags=["shouting", "loud", "commanding"],
    ),
    "laughing": EmotionPreset(
        name="laughing",
        instruct_light="amused, slight chuckle, trying not to laugh",
        instruct_medium="laughing while speaking, infectious amusement",
        instruct_full="uncontrollable laughter, can barely breathe, completely losing it",
        ref_text_light="Ha, okay, that's actually kind of funny. I'll give you that one.",
        ref_text_medium="Hahaha! Oh no... haha, I can't... did you see their face? That was the funniest thing I've ever seen!",
        ref_text_full="Hahahaha! I'm... hahaha... I literally cannot stop... haha... oh god I can't breathe... hahaha... my stomach hurts!",
        tags=["laughing", "amused"],
    ),
    "sarcastic": EmotionPreset(
        name="sarcastic",
        instruct_light="slightly dry, a hint of irony",
        instruct_medium="clearly sarcastic, dry wit, mocking undertone",
        instruct_full="dripping with contemptuous sarcasm, exaggerated mock enthusiasm",
        ref_text_light="Sure, that sounds like a totally reasonable plan. Yep.",
        ref_text_medium="Oh, brilliant. What a fantastic idea. I can't imagine how anything could possibly go wrong with that plan.",
        ref_text_full="Oh WOW, what an ABSOLUTELY GENIUS move! Somebody call the Nobel committee! I have NEVER in my LIFE seen such a masterful display of pure, unadulterated brilliance!",
        tags=["sarcastic", "ironic"],
    ),
    "nervous": EmotionPreset(
        name="nervous",
        instruct_light="slightly hesitant, a touch of uncertainty",
        instruct_medium="anxious, voice slightly unsteady, hesitant",
        instruct_full="stammering with anxiety, voice cracking, on the verge of panic",
        ref_text_light="I think... yeah, I think that should work. Probably. Hopefully.",
        ref_text_medium="I... okay, um, so here's the thing. I don't know exactly how to say this, but... there might be a small problem.",
        ref_text_full="I... I can't... the thing is... oh god, how do I even... okay, okay, um... it's bad. It's really, really bad and I don't... I don't know what to do.",
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
    intensities: list[str] | None = None,
    text_overrides: dict[str, str] | None = None,
) -> list[dict]:
    """Build a batch design request for voice casting.

    Args:
        character_name: Character name (used in prompt naming).
        base_description: Base voice description.
        emotions: Which emotions to generate. Defaults to all.
        intensities: Which intensities per emotion. Defaults to all three.
        text_overrides: Override ref_text for specific "{emotion}_{intensity}" keys.

    Returns:
        List of items suitable for POST /api/v1/voices/design/batch
    """
    emotions = emotions or EMOTION_ORDER
    intensities = intensities or INTENSITIES
    text_overrides = text_overrides or {}
    items = []

    for emotion_name in emotions:
        preset = EMOTION_PRESETS.get(emotion_name)
        if not preset:
            continue

        for intensity in intensities:
            key = f"{emotion_name}_{intensity}"
            name = f"{character_name}_{key}"
            text = text_overrides.get(key, preset.get_ref_text(intensity))
            instruct = preset.get_instruct(base_description, intensity)

            items.append({
                "name": name,
                "text": text,
                "instruct": instruct,
                "language": "English",
                "tags": [emotion_name, intensity] + preset.tags,
            })

    return items
