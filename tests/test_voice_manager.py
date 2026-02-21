"""Tests for VoiceManager (CRUD operations with temp directories)."""

import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def voice_dir(tmp_path):
    return tmp_path / "voices"


@pytest.fixture
def vm(voice_dir):
    from server.voice_manager import VoiceManager
    return VoiceManager(str(voice_dir), engine=None)


def test_empty_catalog(vm):
    assert vm.list_voices() == []


def test_design_voice(vm):
    profile = vm.design_voice("Deep male narrator", name="Narrator")
    assert profile.name == "Narrator"
    assert profile.voice_type == "designed"
    assert profile.description == "Deep male narrator"
    assert profile.voice_id.startswith("designed_")


def test_design_voice_auto_name(vm):
    profile = vm.design_voice("Warm female voice with slight accent")
    assert profile.name == "Warm_female_voice"


def test_list_voices(vm):
    vm.design_voice("Voice A", name="Alice")
    vm.design_voice("Voice B", name="Bob")
    voices = vm.list_voices()
    assert len(voices) == 2
    names = {v["name"] for v in voices}
    assert names == {"Alice", "Bob"}


def test_get_voice_by_id(vm):
    profile = vm.design_voice("Test voice", name="Test")
    found = vm.get_voice(profile.voice_id)
    assert found is not None
    assert found.name == "Test"


def test_get_voice_by_name(vm):
    vm.design_voice("Test voice", name="FindMe")
    found = vm.get_voice("findme")  # case-insensitive
    assert found is not None
    assert found.name == "FindMe"


def test_get_voice_not_found(vm):
    assert vm.get_voice("nonexistent") is None


def test_delete_voice(vm):
    profile = vm.design_voice("To delete", name="Deletable")
    assert vm.delete_voice(profile.voice_id) is True
    assert vm.get_voice(profile.voice_id) is None
    assert len(vm.list_voices()) == 0


def test_delete_nonexistent(vm):
    assert vm.delete_voice("fake_id") is False


def test_clone_voice_from_bytes(vm, voice_dir):
    audio_data = b"RIFF" + b"\x00" * 100  # fake wav
    profile = vm.clone_voice_from_bytes(audio_data, "MyClone", suffix=".wav")
    assert profile.voice_type == "cloned"
    assert profile.name == "MyClone"
    assert profile.reference_audio is not None
    assert Path(profile.reference_audio).exists()


def test_clone_voice_from_file(vm, tmp_path):
    audio_file = tmp_path / "ref.wav"
    audio_file.write_bytes(b"RIFF" + b"\x00" * 100)
    profile = vm.clone_voice(str(audio_file), "FileClone")
    assert profile.voice_type == "cloned"
    assert Path(profile.reference_audio).exists()


def test_clone_voice_missing_file(vm):
    with pytest.raises(FileNotFoundError):
        vm.clone_voice("/nonexistent/path.wav", "Bad")


def test_delete_cloned_voice_removes_file(vm):
    audio_data = b"RIFF" + b"\x00" * 100
    profile = vm.clone_voice_from_bytes(audio_data, "ToDelete")
    ref_path = Path(profile.reference_audio)
    assert ref_path.exists()
    vm.delete_voice(profile.voice_id)
    assert not ref_path.exists()


def test_catalog_persistence(voice_dir):
    from server.voice_manager import VoiceManager

    vm1 = VoiceManager(str(voice_dir), engine=None)
    vm1.design_voice("Persistent voice", name="Persist")

    # Create new instance — should load from disk
    vm2 = VoiceManager(str(voice_dir), engine=None)
    assert len(vm2.list_voices()) == 1
    assert vm2.list_voices()[0]["name"] == "Persist"


def test_initialize_default_cast(vm):
    vm.initialize_default_cast()
    voices = vm.list_voices()
    names = {v["name"] for v in voices}
    assert "Narrator" in names
    assert "Maya" in names
    assert len(voices) == 6  # DEFAULT_VOICE_CAST has 6 entries


def test_initialize_default_cast_idempotent(vm):
    vm.initialize_default_cast()
    count1 = len(vm.list_voices())
    vm.initialize_default_cast()  # second call should not duplicate
    count2 = len(vm.list_voices())
    assert count1 == count2
