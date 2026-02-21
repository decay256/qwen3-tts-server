"""Tests for config module."""

import os


def test_config_loads():
    from server import config
    assert hasattr(config, "AUTH_TOKEN")
    assert hasattr(config, "BRIDGE_URL")
    assert hasattr(config, "RATE_LIMIT")
    assert hasattr(config, "MAX_TEXT_LENGTH")


def test_no_hardcoded_ip():
    from server import config
    # BRIDGE_URL should not contain hardcoded IPs
    assert "104.248" not in config.BRIDGE_URL


def test_rate_limit_is_int():
    from server import config
    assert isinstance(config.RATE_LIMIT, int)
    assert config.RATE_LIMIT > 0


def test_model_hf_ids():
    from server import config
    assert "voice_design" in config.MODEL_HF_IDS
    assert "base" in config.MODEL_HF_IDS


def test_voices_dir_exists():
    from server import config
    assert config.VOICES_DIR.exists()
