"""Tests for voice packaging system."""

import json
import tempfile
import zipfile
from pathlib import Path

import pytest
import soundfile as sf
import numpy as np

from server.voice_manager import VoiceManager
from server.voice_packager import VoicePackager


@pytest.fixture
def temp_dir():
    """Create a temporary directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def voice_manager(temp_dir):
    """Create a VoiceManager with temp directory."""
    vm = VoiceManager(temp_dir / "voices")
    return vm


@pytest.fixture
def voice_packager(voice_manager):
    """Create a VoicePackager."""
    return VoicePackager(voice_manager)


@pytest.fixture
def sample_audio_bytes():
    """Create sample audio data."""
    # Create 1 second of 440Hz sine wave at 24kHz
    sample_rate = 24000
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    audio = np.sin(2 * np.pi * 440 * t) * 0.5
    
    # Convert to bytes (WAV format)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, audio, sample_rate)
        return Path(tmp.name).read_bytes()


def test_export_designed_voice_package(voice_packager, temp_dir):
    """Test exporting a designed voice as a package."""
    # Create a designed voice
    voice = voice_packager.voice_manager.design_voice(
        description="Test voice for packaging",
        name="TestVoice"
    )
    
    # Export the package
    package_path = voice_packager.export_package(voice.voice_id, temp_dir / "test.voicepkg.zip")
    
    assert package_path.exists()
    assert package_path.suffix == ".zip"
    
    # Verify package contents
    with zipfile.ZipFile(package_path, "r") as zf:
        files = zf.namelist()
        assert "meta.json" in files
        assert "samples/.gitkeep" in files
        
        # Check metadata
        meta_content = zf.read("meta.json").decode("utf-8")
        meta = json.loads(meta_content)
        
        assert meta["format_version"] == 1
        assert meta["voice_id"] == voice.voice_id
        assert meta["name"] == "TestVoice"
        assert meta["voice_type"] == "designed"
        assert meta["design_description"] == "Test voice for packaging"
        assert meta["design_language"] == "English"
        assert meta["source"] == "voice_design"
        assert "package_created_at" in meta


def test_export_cloned_voice_package(voice_packager, temp_dir, sample_audio_bytes):
    """Test exporting a cloned voice as a package."""
    # Create a cloned voice
    voice = voice_packager.voice_manager.clone_voice_from_bytes(
        sample_audio_bytes, "ClonedVoice"
    )
    
    # Export the package
    package_path = voice_packager.export_package(voice.voice_id, temp_dir / "cloned.voicepkg.zip")
    
    assert package_path.exists()
    
    # Verify package contents
    with zipfile.ZipFile(package_path, "r") as zf:
        files = zf.namelist()
        assert "meta.json" in files
        assert "ref.wav" in files
        
        # Check metadata
        meta_content = zf.read("meta.json").decode("utf-8")
        meta = json.loads(meta_content)
        
        assert meta["voice_type"] == "cloned"
        assert meta["name"] == "ClonedVoice"
        assert meta["source"] == "user_upload"
        assert "ref_duration_s" in meta
        assert "ref_sample_rate" in meta


def test_import_designed_voice_package(voice_packager, temp_dir):
    """Test importing a designed voice package."""
    # Create and export a voice
    original_voice = voice_packager.voice_manager.design_voice(
        description="Original voice",
        name="Original"
    )
    package_path = voice_packager.export_package(original_voice.voice_id)
    
    # Clear the voice manager
    voice_packager.voice_manager._voices.clear()
    voice_packager.voice_manager._save_catalog()
    
    # Import the package
    imported_voice = voice_packager.import_package(package_path)
    
    assert imported_voice.voice_id == original_voice.voice_id
    assert imported_voice.name == "Original"
    assert imported_voice.voice_type == "designed"
    assert imported_voice.description == "Original voice"
    
    # Verify it's in the catalog
    voices = voice_packager.voice_manager.list_voices()
    assert len(voices) == 1
    assert voices[0]["name"] == "Original"


def test_import_cloned_voice_package(voice_packager, temp_dir, sample_audio_bytes):
    """Test importing a cloned voice package."""
    # Create and export a cloned voice
    original_voice = voice_packager.voice_manager.clone_voice_from_bytes(
        sample_audio_bytes, "OriginalClone"
    )
    original_voice.ref_text = "Test transcript"
    voice_packager.voice_manager._save_catalog()
    
    package_path = voice_packager.export_package(original_voice.voice_id)
    
    # Clear the voice manager
    voice_packager.voice_manager._voices.clear()
    voice_packager.voice_manager._save_catalog()
    
    # Import the package
    imported_voice = voice_packager.import_package(package_path)
    
    assert imported_voice.voice_id == original_voice.voice_id
    assert imported_voice.name == "OriginalClone"
    assert imported_voice.voice_type == "cloned"
    assert imported_voice.ref_text == "Test transcript"
    assert imported_voice.reference_audio is not None
    assert Path(imported_voice.reference_audio).exists()


def test_import_package_from_bytes(voice_packager, temp_dir):
    """Test importing a package from raw bytes."""
    # Create and export a voice
    voice = voice_packager.voice_manager.design_voice("Test", "TestBytesImport")
    package_path = voice_packager.export_package(voice.voice_id)
    
    # Read package bytes
    package_bytes = package_path.read_bytes()
    
    # Clear voice manager
    voice_packager.voice_manager._voices.clear()
    voice_packager.voice_manager._save_catalog()
    
    # Import from bytes
    imported_voice = voice_packager.import_package(package_bytes)
    
    assert imported_voice.name == "TestBytesImport"
    assert imported_voice.voice_type == "designed"


def test_export_all_packages(voice_packager, temp_dir):
    """Test exporting all voices as packages."""
    # Create multiple voices
    voice1 = voice_packager.voice_manager.design_voice("Voice 1", "V1")
    voice2 = voice_packager.voice_manager.design_voice("Voice 2", "V2")
    
    # Export all
    output_dir = temp_dir / "all_packages"
    packages = voice_packager.export_all(output_dir)
    
    assert len(packages) == 2
    for package_path in packages:
        assert package_path.exists()
        assert package_path.suffix == ".zip"
        assert package_path.parent == output_dir


def test_invalid_package_import(voice_packager):
    """Test importing invalid packages."""
    # Test missing meta.json
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        with zipfile.ZipFile(tmp.name, "w") as zf:
            zf.writestr("dummy.txt", "not a valid package")
        
        with pytest.raises(ValueError, match="missing meta.json"):
            voice_packager.import_package(tmp.name)
    
    # Test invalid metadata
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        with zipfile.ZipFile(tmp.name, "w") as zf:
            invalid_meta = {"format_version": 1}  # Missing required fields
            zf.writestr("meta.json", json.dumps(invalid_meta))
        
        with pytest.raises(ValueError, match="missing required field"):
            voice_packager.import_package(tmp.name)


def test_duplicate_voice_import(voice_packager):
    """Test importing a voice that already exists."""
    # Create a voice
    voice = voice_packager.voice_manager.design_voice("Test", "Duplicate")
    package_path = voice_packager.export_package(voice.voice_id)
    
    # Try to import again (should fail)
    with pytest.raises(ValueError, match="Voice already exists"):
        voice_packager.import_package(package_path)


def test_export_nonexistent_voice(voice_packager):
    """Test exporting a voice that doesn't exist."""
    with pytest.raises(ValueError, match="Voice not found"):
        voice_packager.export_package("nonexistent_voice_id")


def test_package_with_transcript_file(voice_packager, sample_audio_bytes, temp_dir):
    """Test that transcript is written to ref_transcript.txt in package."""
    # Create cloned voice with transcript
    voice = voice_packager.voice_manager.clone_voice_from_bytes(
        sample_audio_bytes, "VoiceWithTranscript"
    )
    voice.ref_text = "This is the reference transcript."
    voice_packager.voice_manager._save_catalog()
    
    # Export package
    package_path = voice_packager.export_package(voice.voice_id, temp_dir / "transcript.voicepkg.zip")
    
    # Verify transcript file exists in package
    with zipfile.ZipFile(package_path, "r") as zf:
        files = zf.namelist()
        assert "ref_transcript.txt" in files
        
        transcript_content = zf.read("ref_transcript.txt").decode("utf-8")
        assert transcript_content == "This is the reference transcript."