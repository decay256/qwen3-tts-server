"""LLM-assisted voice prompt refinement.

Takes user feedback about a voice clip and generates an improved instruct string.
Supports OpenAI and Anthropic as configurable providers.
"""

import logging
from typing import Optional

from web.app.core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a voice design expert for a text-to-speech system.

The TTS system uses an "instruct" string to control voice characteristics. The instruct
describes physical voice traits (pitch, texture, accent) combined with emotional/delivery
direction (angry, whispering, tender, etc.).

Rules for good instruct strings:
- Base description should contain ONLY physical traits: pitch, texture, resonance, accent
- Emotion/delivery words should be separate from the base description
- Avoid mood words (sultry, warm, seductive) in base descriptions — they fight emotion modifiers
- Be specific and concrete, not vague
- Stronger emotions should use more intense language ("volcanic rage" vs "slightly annoyed")

When the user describes a problem, adjust the instruct to fix it while preserving what works."""

USER_TEMPLATE = """Current instruct: "{current_instruct}"
Current base description: "{base_description}"
Reference text that was spoken: "{ref_text}"

User feedback: "{feedback}"

Respond with ONLY a JSON object (no markdown, no explanation):
{{
  "new_instruct": "the improved full instruct string (base + emotion combined)",
  "new_base_description": "updated base description if needed, or null",
  "explanation": "brief explanation of what you changed and why"
}}"""


async def refine_prompt(
    current_instruct: str,
    base_description: str,
    ref_text: str,
    feedback: str,
) -> dict:
    """Use LLM to refine a voice instruct based on user feedback.

    Args:
        current_instruct: The current full instruct string.
        base_description: The base voice description (physical traits).
        ref_text: The text that was spoken with this instruct.
        feedback: User's description of what's wrong.

    Returns:
        Dict with "new_instruct", "new_base_description" (or None), "explanation".

    Raises:
        ValueError: If LLM response can't be parsed.
        RuntimeError: If LLM call fails.
    """
    import json

    user_msg = USER_TEMPLATE.format(
        current_instruct=current_instruct,
        base_description=base_description,
        ref_text=ref_text,
        feedback=feedback,
    )

    if settings.llm_provider == "anthropic":
        result = await _call_anthropic(user_msg)
    else:
        result = await _call_openai(user_msg)

    # Parse JSON response
    try:
        # Strip markdown code fences if present
        text = result.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(text)
    except (json.JSONDecodeError, IndexError) as e:
        raise ValueError(f"Failed to parse LLM response: {result}") from e


async def _call_openai(user_msg: str) -> str:
    """Call OpenAI API."""
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.7,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _call_anthropic(user_msg: str) -> str:
    """Call Anthropic API."""
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": settings.llm_model,
                "max_tokens": 500,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_msg}],
            },
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]
