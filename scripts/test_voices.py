#!/usr/bin/env python3
"""Test all voice modes against the running server."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import yaml

from client.tts_client import TTSClient


async def run_tests(base_url: str, api_key: str) -> None:
    """Run through all voice-related API tests.

    Args:
        base_url: Relay server URL.
        api_key: API key.
    """
    async with TTSClient(base_url, api_key) as client:
        # 1. Status check
        print("=" * 50)
        print("1. Checking server status...")
        try:
            status = await client.status()
            print(f"   Relay: {status.get('relay')}")
            print(f"   Tunnel connected: {status.get('tunnel_connected')}")
            local = status.get("local", {})
            if local:
                print(f"   GPU: {local.get('gpu', 'N/A')}")
                print(f"   VRAM: {local.get('vram_used_gb', 0):.1f} / {local.get('vram_total_gb', 0):.1f} GB")
                print(f"   Models loaded: {local.get('models_loaded', [])}")
                print(f"   Engine ready: {local.get('engine_ready', False)}")
        except Exception as e:
            print(f"   ❌ Status check failed: {e}")
            return

        if not status.get("tunnel_connected"):
            print("\n❌ No GPU server connected. Start the local server first.")
            return

        # 2. List voices
        print("\n" + "=" * 50)
        print("2. Listing voices...")
        try:
            voices = await client.list_voices()
            for v in voices:
                print(f"   [{v.voice_type}] {v.name} ({v.voice_id})")
                if v.description:
                    print(f"       → {v.description[:60]}...")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # 3. Design a new voice
        print("\n" + "=" * 50)
        print("3. Designing a test voice...")
        try:
            voice = await client.design_voice(
                description="Cheerful young woman with a bright, energetic tone",
                name="TestVoice",
            )
            print(f"   ✅ Created: {voice.name} ({voice.voice_id})")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # 4. Synthesize with each default voice
        print("\n" + "=" * 50)
        print("4. Testing synthesis with default voices...")

        test_text = "Hello! This is a test of the Qwen3 text-to-speech system. How does this voice sound?"

        for voice_name in ["Narrator", "Maya", "Elena", "Chen", "Raj", "Kim"]:
            try:
                result = await client.synthesize(
                    text=test_text,
                    voice_id=voice_name,
                    format="mp3",
                )
                output_path = Path(f"test_output_{voice_name.lower()}.mp3")
                result.save(output_path)
                print(f"   ✅ {voice_name}: {result.duration_seconds:.1f}s → {output_path}")
            except Exception as e:
                print(f"   ❌ {voice_name}: {e}")

        # 5. Synthesize with instructions
        print("\n" + "=" * 50)
        print("5. Testing synthesis with instructions...")
        try:
            result = await client.synthesize(
                text="I can't believe this actually works!",
                voice_id="Maya",
                instructions="speak with excitement and wonder",
                format="mp3",
            )
            result.save("test_output_instructions.mp3")
            print(f"   ✅ With instructions: {result.duration_seconds:.1f}s")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        print("\n" + "=" * 50)
        print("✅ All tests complete!")


def main() -> None:
    """Entry point."""
    config_path = Path("config.yaml")
    if not config_path.exists():
        print("❌ config.yaml not found. Run generate_keys.py first.")
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    remote = config.get("remote", {})
    scheme = "https" if remote.get("tls") else "http"
    host = remote.get("host", "localhost")
    port = remote.get("port", 9800)
    base_url = f"{scheme}://{host}:{port}"

    asyncio.run(run_tests(base_url, config["api_key"]))


if __name__ == "__main__":
    main()
