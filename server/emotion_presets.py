"""Voice casting presets: emotions (2 intensities) + modes (1 intensity).

Emotions have medium and intense variants.
Modes are singular (always high intensity / fully committed).

Both instruct AND text reinforce the target expression — doubling the signal
to the VoiceDesign model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EmotionPreset:
    """An emotion with medium and intense variants."""
    name: str
    instruct_medium: str
    instruct_intense: str
    ref_text_medium: str
    ref_text_intense: str
    tags: list[str] = field(default_factory=list)

    def get_instruct(self, base_description: str, intensity: str = "medium") -> str:
        instruct = self.instruct_intense if intensity == "intense" else self.instruct_medium
        return f"{base_description}, {instruct}"

    def get_ref_text(self, intensity: str = "medium") -> str:
        return self.ref_text_intense if intensity == "intense" else self.ref_text_medium


@dataclass
class ModePreset:
    """A delivery/physical/context mode — always at full commitment."""
    name: str
    instruct: str
    ref_text: str
    tags: list[str] = field(default_factory=list)

    def get_instruct(self, base_description: str) -> str:
        return f"{base_description}, {self.instruct}"

    def get_ref_text(self) -> str:
        return self.ref_text


EMOTION_INTENSITIES = ["medium", "intense"]


# ── Emotions (9 × 2 = 18 entries) ──────────────────────────────────

EMOTION_PRESETS: dict[str, EmotionPreset] = {
    "happy": EmotionPreset(
        name="happy",
        instruct_medium="genuinely happy, warm smile in the voice, upbeat energy",
        instruct_intense="overwhelmed with joy, voice cracking with elation, barely containing euphoria, laughing between words",
        ref_text_medium="Oh my god, it actually worked! I'm so happy right now, this is the best news I've had all year!",
        ref_text_intense="I can't believe it! I can't! This is the most incredible thing that has ever happened to me! I'm shaking, I'm literally shaking with happiness right now!",
        tags=["happy", "joy"],
    ),
    "angry": EmotionPreset(
        name="angry",
        instruct_medium="angry, clipped words, barely containing frustration, jaw clenched",
        instruct_intense="volcanic rage, SCREAMING, spit flying, veins bulging, completely unhinged fury, voice tearing",
        ref_text_medium="No. Absolutely not. You had one job, one simple task, and you couldn't even manage that. This is unacceptable.",
        ref_text_intense="HOW DARE YOU! After EVERYTHING I sacrificed! You DESTROYED it! You destroyed EVERYTHING! I will NEVER forgive you for this! NEVER!",
        tags=["angry", "rage"],
    ),
    "afraid": EmotionPreset(
        name="afraid",
        instruct_medium="scared, voice trembling, growing dread, breath quickening",
        instruct_intense="paralyzed with terror, hyperventilating, voice a strangled whisper then breaking into panic, animal fear",
        ref_text_medium="Something's wrong. Something's very wrong. We need to get out of here, right now. Please, we have to go.",
        ref_text_intense="Oh god oh god oh god it's here it's RIGHT HERE don't move don't BREATHE I can hear it I can hear it breathing oh god please no please no PLEASE!",
        tags=["afraid", "terror", "panic"],
    ),
    "sad": EmotionPreset(
        name="sad",
        instruct_medium="sad, voice heavy and slow, weighted with disappointment, aching",
        instruct_intense="devastated, voice shattering, words dissolving into sobs, drowning in grief, can barely form sentences",
        ref_text_medium="I waited so long... and now it's just... gone. All of it. I don't even know what to say anymore.",
        ref_text_intense="They're gone. They're really gone and they're NEVER coming back. I can't... I can't breathe... everything is gone... everything...",
        tags=["sad", "grief", "devastated"],
    ),
    "awe": EmotionPreset(
        name="awe",
        instruct_medium="breathless wonder, reverence, the enormity of it sinking in slowly",
        instruct_intense="struck dumb by the sublime, trembling, voice barely a whisper, tears forming from sheer scale of what is being witnessed",
        ref_text_medium="It went down for kilometers. Structure after structure, branching and folding in on itself. The geometry was impossible and yet there it was, undeniably real.",
        ref_text_intense="I have no words. I have... nothing. In four billion years nothing on Earth ever made anything like this. I'm looking at something that shouldn't exist and I'm weeping because it's the most beautiful thing I've ever seen.",
        tags=["awe", "wonder", "sublime"],
    ),
    "tender": EmotionPreset(
        name="tender",
        instruct_medium="soft, full of warmth and affection, caring, gentle touch in the voice",
        instruct_intense="overflowing with love, voice barely above a breath, intimate, as if holding something impossibly fragile and precious",
        ref_text_medium="Hey... it's okay. I'm right here. You don't have to be strong all the time. I've got you.",
        ref_text_intense="I love you. I love you so much it physically hurts. You are the single most important thing in my entire universe and I need you to feel that. Always. Every second.",
        tags=["tender", "love", "intimate"],
    ),
    "sarcastic": EmotionPreset(
        name="sarcastic",
        instruct_medium="clearly sarcastic, dry wit, mocking undertone, one eyebrow raised",
        instruct_intense="dripping with venom, contemptuous sarcasm weaponized, exaggerated mock enthusiasm so thick it burns",
        ref_text_medium="Oh, brilliant. What a fantastic idea. I can't imagine how anything could possibly go wrong with that plan.",
        ref_text_intense="Oh WOW, what an ABSOLUTELY GENIUS move! Somebody alert the Nobel committee! I have NEVER in my ENTIRE LIFE witnessed such a masterful display of pure, unadulterated, weapons-grade STUPIDITY!",
        tags=["sarcastic", "mocking", "contempt"],
    ),
    "manic": EmotionPreset(
        name="manic",
        instruct_medium="rapid, breathless, swept up in escalating events, momentum building",
        instruct_intense="frenetic torrent, words crashing into each other, no pauses, everything happening at once, losing coherence from sheer speed",
        ref_text_medium="Everything is accelerating. The readings are shifting, the patterns are changing, and I'm running between three consoles trying to keep up with all of it.",
        ref_text_intense="Alarms everywhere pressure breach hull integrity dropping people screaming coordinates the core is shifting EVERYTHING is shifting and we have maybe thirty seconds to figure this out or we're ALL dead!",
        tags=["manic", "frenetic", "urgent"],
    ),
    "exhausted": EmotionPreset(
        name="exhausted",
        instruct_medium="drained, heavy, the weight of sustained effort showing, running on fumes",
        instruct_intense="completely hollowed out, flat, soul emptied, speaking from the bottom of an empty well, barely animate",
        ref_text_medium="Three weeks of double shifts. Everything feels smaller every day. The work matters more than sleep but the body disagrees.",
        ref_text_intense="There is nothing left. Not in me. Not anywhere. Just the hum of machines and time passing and me sitting here because I forgot how to stand up. I forgot how to care.",
        tags=["exhausted", "depleted", "empty"],
    ),
}

EMOTION_ORDER = list(EMOTION_PRESETS.keys())


# ── Modes (15 × 1 = 15 entries) ────────────────────────────────────

MODE_PRESETS: dict[str, ModePreset] = {
    "crying": ModePreset(
        name="crying",
        instruct="sobbing uncontrollably, voice shattering, gasping for air between sobs, wet ragged breathing, tears choking words",
        ref_text="I tried... I tried so hard to hold it together but I... oh god... I can't stop... I'm so sorry... I'm so sorry for everything...",
        tags=["crying", "sobbing", "physical"],
    ),
    "screaming": ModePreset(
        name="screaming",
        instruct="SCREAMING at absolute full volume, raw throat, desperate, vocal cords straining to breaking point",
        ref_text="GET AWAY FROM HER! NO! STOP! SOMEBODY HELP US! RUN! GET TO THE DOOR NOW! MOVE MOVE MOVE! OH GOD PLEASE HELP!",
        tags=["screaming", "physical"],
    ),
    "gasping": ModePreset(
        name="gasping",
        instruct="gasping for air, post-exertion, words squeezed between desperate breaths, winded, lungs burning",
        ref_text="I can't... keep... just give me a second... ran the whole... the whole way here... oh god I think I'm going to... just... one second...",
        tags=["gasping", "panting", "physical"],
    ),
    "choking": ModePreset(
        name="choking",
        instruct="voice strangled, throat constricted, fighting to get words out, under physical duress, strained and thin",
        ref_text="Can't... breathe... something's... wrong... help me... please... I can't... get it... off...",
        tags=["choking", "strained", "physical"],
    ),
    "stuttering": ModePreset(
        name="stuttering",
        instruct="stammering badly, words catching and repeating, nervous energy making speech fragment, losing control of delivery",
        ref_text="I d-d-didn't mean to, I swear I j-just... it was an acc-accident, please, you have to b-believe me, I w-wasn't trying to...",
        tags=["stuttering", "nervous", "physical"],
    ),
    "whispering": ModePreset(
        name="whispering",
        instruct="pure unvoiced whisper, zero vocal cord vibration, only shaped breath and air, no bass no resonance no phonation at all, like a secret you'd die to protect",
        ref_text="Don't... breathe... it's right outside the door... if it hears us... just close your eyes and don't move a muscle...",
        tags=["whispering", "quiet"],
    ),
    "singsong": ModePreset(
        name="singsong",
        instruct="lilting sing-song cadence, nursery-rhyme rhythm, eerie and unsettling, playfully menacing",
        ref_text="One little astronaut, lost in the dark... two little astronauts, missing the mark... three little astronauts, falling apart... who will be left when we get to the start?",
        tags=["singsong", "eerie", "delivery"],
    ),
    "slurred": ModePreset(
        name="slurred",
        instruct="slurred speech, words melting into each other, drugged or concussed, losing focus mid-sentence, drifting",
        ref_text="No no no lissten... I'm fine, I'm totally... the lights are all... wobbly? Is that... what was I saying? Something about the... the thing... never mind...",
        tags=["slurred", "drugged", "delivery"],
    ),
    "shouting": ModePreset(
        name="shouting",
        instruct="SHOUTING, projecting voice across a massive space, commanding, cutting through noise, full diaphragm",
        ref_text="EVERYONE LISTEN UP! We have EXACTLY five minutes! I need teams at every exit, NOW! Nobody moves until I give the signal! Is that CLEAR?",
        tags=["shouting", "commanding", "delivery"],
    ),
    "radio": ModePreset(
        name="radio",
        instruct="crisp radio comms voice, clipped professional delivery, military brevity, terse and precise",
        ref_text="Bravo six actual, this is overwatch. Contact bearing zero-niner-five, range two hundred meters. Two tangos moving east. Request clearance to engage. Over.",
        tags=["radio", "comms", "military", "context"],
    ),
    "narration": ModePreset(
        name="narration",
        instruct="measured storytelling voice, authoritative narrator, pacing words for dramatic weight, letting silence work",
        ref_text="It was the kind of silence that follows an explosion. Not empty. Full. Thick with the memory of sound, with the echo of what had just been lost.",
        tags=["narration", "storytelling", "context"],
    ),
    "distant": ModePreset(
        name="distant",
        instruct="projecting across a large space, shouting to someone far away, voice carrying over distance, slightly strained",
        ref_text="CAN YOU HEAR ME? I'M OVER HERE! FOLLOW MY VOICE! KEEP WALKING TOWARD THE LIGHT! YOU'RE ALMOST THERE!",
        tags=["distant", "projecting", "context"],
    ),
}

MODE_ORDER = list(MODE_PRESETS.keys())


# ── Casting helpers ─────────────────────────────────────────────────

def build_casting_batch(
    character_name: str,
    base_description: str,
    emotions: list[str] | None = None,
    intensities: list[str] | None = None,
    modes: list[str] | None = None,
    text_overrides: dict[str, str] | None = None,
) -> list[dict]:
    """Build a batch design request for voice casting.

    Args:
        character_name: Character name (used in prompt naming).
        base_description: Base voice description (physical traits only).
        emotions: Which emotions to generate. Defaults to all.
        intensities: Which intensities per emotion. Defaults to ["medium", "intense"].
        modes: Which modes to generate. Defaults to all. Pass [] to skip modes.
        text_overrides: Override ref_text for specific keys like "angry_intense" or "screaming".

    Returns:
        List of items suitable for POST /api/v1/voices/design/batch
    """
    emotions = emotions if emotions is not None else EMOTION_ORDER
    intensities = intensities or EMOTION_INTENSITIES
    modes = modes if modes is not None else MODE_ORDER
    text_overrides = text_overrides or {}
    items = []

    # Emotions × intensities
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

    # Modes (single intensity)
    for mode_name in modes:
        preset = MODE_PRESETS.get(mode_name)
        if not preset:
            continue
        key = mode_name
        name = f"{character_name}_{key}"
        text = text_overrides.get(key, preset.get_ref_text())
        instruct = preset.get_instruct(base_description)
        items.append({
            "name": name,
            "text": text,
            "instruct": instruct,
            "language": "English",
            "tags": [mode_name] + preset.tags,
        })

    return items
