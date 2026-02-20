#!/usr/bin/env python3
"""Generate API keys and create config files for both local and remote servers."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

from server.auth import generate_api_key


def main() -> None:
    """Generate API key and create config.yaml from template."""
    config_path = Path("config.yaml")
    example_path = Path("config.example.yaml")

    if config_path.exists():
        print(f"⚠️  config.yaml already exists.")
        answer = input("Overwrite? (y/N): ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    if not example_path.exists():
        print("❌ config.example.yaml not found. Are you in the project root?")
        sys.exit(1)

    # Generate API key
    api_key = generate_api_key()
    print(f"\n🔑 Generated API key: {api_key}")

    # Load example config and set the key
    with open(example_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config["api_key"] = api_key

    # Write config
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"\n✅ Config written to {config_path}")
    print("\n📋 Next steps:")
    print("  1. Edit config.yaml to set your remote server host/port")
    print("  2. Copy config.yaml to both local and remote machines")
    print("  3. Start remote relay:  python -m server.remote_relay")
    print("  4. Start local server:  python -m server.local_server")
    print(f"\n🔐 Keep your API key safe: {api_key[:16]}...")


if __name__ == "__main__":
    main()
