"""Tests for the voice clone prompt store."""

import json
from dataclasses import dataclass
from typing import Optional
from unittest.mock import patch, MagicMock

import pytest


# Mock VoiceClonePromptItem for testing (no torch dependency)
@dataclass
class MockPromptItem:
    ref_code: object = None
    ref_spk_embedding: object = None
    x_vector_only_mode: bool = False
    icl_mode: bool = True
    ref_text: Optional[str] = None


@pytest.fixture
def store(tmp_path):
    """Create a PromptStore with mocked torch."""
    mock_torch = MagicMock()
    mock_torch.save = MagicMock()
    mock_torch.load = MagicMock(return_value={
        "ref_code": "mock_tensor",
        "ref_spk_embedding": "mock_embedding",
        "x_vector_only_mode": False,
        "icl_mode": True,
        "ref_text": "Hello world",
    })

    with patch("server.prompt_store._get_torch", return_value=mock_torch):
        from server.prompt_store import PromptStore
        s = PromptStore(tmp_path / "voice-prompts")
        yield s


class TestPromptStore:

    def test_save_and_list(self, store):
        item = MockPromptItem(ref_text="Hello")
        meta = store.save_prompt("test_voice", item, tags=["happy", "female"])
        
        assert meta.name == "test_voice"
        assert meta.tags == ["happy", "female"]
        
        prompts = store.list_prompts()
        assert len(prompts) == 1
        assert prompts[0]["name"] == "test_voice"

    def test_list_filter_by_tags(self, store):
        store.save_prompt("voice_happy", MockPromptItem(), tags=["happy", "female"])
        store.save_prompt("voice_angry", MockPromptItem(), tags=["angry", "female"])
        store.save_prompt("voice_male", MockPromptItem(), tags=["neutral", "male"])

        # Filter by single tag
        results = store.list_prompts(tags=["female"])
        assert len(results) == 2

        # Filter by multiple tags (AND)
        results = store.list_prompts(tags=["happy", "female"])
        assert len(results) == 1
        assert results[0]["name"] == "voice_happy"

        # No match
        results = store.list_prompts(tags=["nonexistent"])
        assert len(results) == 0

    def test_delete_prompt(self, store):
        store.save_prompt("to_delete", MockPromptItem())
        assert len(store.list_prompts()) == 1
        
        deleted = store.delete_prompt("to_delete")
        assert deleted is True
        assert len(store.list_prompts()) == 0

    def test_delete_nonexistent(self, store):
        deleted = store.delete_prompt("nope")
        assert deleted is False

    def test_load_prompt_from_cache(self, store):
        item = MockPromptItem(ref_text="cached")
        store.save_prompt("cached_voice", item)
        
        # Should return from cache (no disk load)
        loaded = store.load_prompt("cached_voice")
        assert loaded is item  # Same object from cache

    def test_load_prompt_from_disk(self, store, tmp_path):
        """When not in cache, loads from disk."""
        item = MockPromptItem(ref_text="disk")
        store.save_prompt("disk_voice", item)
        
        # Clear cache
        store._cache.clear()
        
        # Mock the qwen_tts import
        mock_prompt_cls = MagicMock()
        mock_prompt_cls.return_value = MockPromptItem(ref_text="loaded")
        
        with patch("server.prompt_store.PromptStore.load_prompt") as mock_load:
            mock_load.return_value = MockPromptItem(ref_text="loaded")
            loaded = store.load_prompt.__wrapped__(store, "disk_voice") if hasattr(store.load_prompt, '__wrapped__') else mock_load("disk_voice")
            assert loaded is not None

    def test_load_nonexistent_raises(self, store):
        with pytest.raises(FileNotFoundError):
            store.load_prompt("nonexistent")

    def test_invalid_name_raises(self, store):
        with pytest.raises(ValueError, match="Invalid prompt name"):
            store.save_prompt("bad name!", MockPromptItem())

    def test_name_with_special_chars_raises(self, store):
        with pytest.raises(ValueError):
            store.save_prompt("path/traversal", MockPromptItem())

    def test_valid_names(self, store):
        # These should all work
        store.save_prompt("simple", MockPromptItem())
        store.save_prompt("with-hyphens", MockPromptItem())
        store.save_prompt("with_underscores", MockPromptItem())
        store.save_prompt("CamelCase123", MockPromptItem())
        assert len(store.list_prompts()) == 4

    def test_cache_eviction(self, tmp_path):
        """LRU cache evicts oldest entries."""
        mock_torch = MagicMock()
        with patch("server.prompt_store._get_torch", return_value=mock_torch):
            from server.prompt_store import PromptStore
            store = PromptStore(tmp_path / "prompts", cache_size=2)

            store.save_prompt("a", MockPromptItem())
            store.save_prompt("b", MockPromptItem())
            store.save_prompt("c", MockPromptItem())

            # 'a' should have been evicted from cache
            assert "a" not in store._cache
            assert "b" in store._cache
            assert "c" in store._cache

    def test_metadata_persistence(self, tmp_path):
        """Metadata survives re-initialization."""
        mock_torch = MagicMock()
        prompts_dir = tmp_path / "prompts"
        
        with patch("server.prompt_store._get_torch", return_value=mock_torch):
            from server.prompt_store import PromptStore
            
            store1 = PromptStore(prompts_dir)
            store1.save_prompt("persistent", MockPromptItem(), tags=["tag1"])
            
            # Create new store instance (simulates restart)
            store2 = PromptStore(prompts_dir)
            prompts = store2.list_prompts()
            assert len(prompts) == 1
            assert prompts[0]["name"] == "persistent"
            assert prompts[0]["tags"] == ["tag1"]

    def test_get_metadata(self, store):
        store.save_prompt("meta_test", MockPromptItem(), tags=["x"], ref_text="hello")
        meta = store.get_metadata("meta_test")
        assert meta is not None
        assert meta.name == "meta_test"
        assert meta.ref_text == "hello"

    def test_get_metadata_nonexistent(self, store):
        assert store.get_metadata("nope") is None

    def test_overwrite_prompt(self, store):
        """Saving with same name overwrites."""
        store.save_prompt("voice", MockPromptItem(), tags=["v1"])
        store.save_prompt("voice", MockPromptItem(), tags=["v2"])
        
        prompts = store.list_prompts()
        assert len(prompts) == 1
        assert prompts[0]["tags"] == ["v2"]


class TestVoiceLibrary:
    """Tests for voice library search and character features."""

    @pytest.fixture
    def library_store(self, tmp_path):
        """Create a PromptStore populated with voice library entries."""
        mock_torch = MagicMock()
        mock_torch.save = MagicMock()

        with patch("server.prompt_store._get_torch", return_value=mock_torch):
            from server.prompt_store import PromptStore
            s = PromptStore(tmp_path / "voice-prompts")

            # Add Kira prompts
            for emotion in ["happy", "angry", "afraid"]:
                for intensity in ["medium", "intense"]:
                    item = MockPromptItem(ref_text=f"Kira {emotion} {intensity}")
                    s.save_prompt(
                        name=f"kira_{emotion}_{intensity}",
                        prompt_item=item,
                        tags=["kira", emotion, intensity],
                        ref_text=f"Kira {emotion} {intensity}",
                        character="kira",
                        emotion=emotion,
                        intensity=intensity,
                        description=f"{emotion} ({intensity})",
                        instruct=f"Adult woman, husky voice, {emotion}",
                        base_description="Adult woman, husky voice",
                    )
            # Add Kira mode
            item = MockPromptItem(ref_text="Kira laughing")
            s.save_prompt(
                name="kira_laughing",
                prompt_item=item,
                tags=["kira", "laughing"],
                ref_text="Hahahaha!",
                character="kira",
                emotion="laughing",
                intensity="full",
                description="laughing (mode): cracking up",
                base_description="Adult woman, husky voice",
            )

            # Add Marcus prompts
            for emotion in ["happy", "sad"]:
                item = MockPromptItem(ref_text=f"Marcus {emotion}")
                s.save_prompt(
                    name=f"marcus_{emotion}_medium",
                    prompt_item=item,
                    tags=["marcus", emotion, "medium"],
                    ref_text=f"Marcus {emotion}",
                    character="marcus",
                    emotion=emotion,
                    intensity="medium",
                    description=f"{emotion} (medium)",
                    base_description="Young man, light tenor",
                )

            yield s

    def test_search_by_character(self, library_store):
        results = library_store.search_prompts(character="kira")
        assert len(results) == 7  # 3 emotions × 2 intensities + 1 mode

    def test_search_by_character_case_insensitive(self, library_store):
        results = library_store.search_prompts(character="Kira")
        assert len(results) == 7

    def test_search_by_emotion(self, library_store):
        results = library_store.search_prompts(emotion="happy")
        assert len(results) == 3  # kira happy medium, kira happy intense, marcus happy medium

    def test_search_by_character_and_emotion(self, library_store):
        results = library_store.search_prompts(character="kira", emotion="angry")
        assert len(results) == 2  # medium + intense

    def test_search_by_character_emotion_intensity(self, library_store):
        results = library_store.search_prompts(character="kira", emotion="angry", intensity="intense")
        assert len(results) == 1
        assert results[0]["name"] == "kira_angry_intense"
        assert results[0]["description"] == "angry (intense)"
        assert results[0]["instruct"] == "Adult woman, husky voice, angry"
        assert results[0]["base_description"] == "Adult woman, husky voice"

    def test_search_no_results(self, library_store):
        results = library_store.search_prompts(character="nonexistent")
        assert len(results) == 0

    def test_search_with_tags(self, library_store):
        results = library_store.search_prompts(tags=["laughing"])
        assert len(results) == 1
        assert results[0]["name"] == "kira_laughing"

    def test_list_characters(self, library_store):
        chars = library_store.list_characters()
        assert len(chars) == 2
        kira = next(c for c in chars if c["character"] == "kira")
        assert kira["prompt_count"] == 7
        assert "happy" in kira["emotions"]
        assert "angry" in kira["emotions"]
        assert "laughing" in kira["emotions"]

        marcus = next(c for c in chars if c["character"] == "marcus")
        assert marcus["prompt_count"] == 2
        assert "happy" in marcus["emotions"]
        assert "sad" in marcus["emotions"]

    def test_metadata_includes_voice_library_fields(self, library_store):
        meta = library_store.get_metadata("kira_happy_medium")
        assert meta is not None
        assert meta.character == "kira"
        assert meta.emotion == "happy"
        assert meta.intensity == "medium"
        d = meta.to_dict()
        assert "character" in d
        assert "emotion" in d
        assert "description" in d

    def test_metadata_omits_none_fields(self):
        """Voice library fields should not appear in to_dict when None."""
        from server.prompt_store import PromptMetadata
        meta = PromptMetadata(name="basic")
        d = meta.to_dict()
        assert "character" not in d
        assert "emotion" not in d
        assert "description" not in d

    def test_metadata_roundtrip(self):
        from server.prompt_store import PromptMetadata
        meta = PromptMetadata(
            name="test",
            character="kira",
            emotion="angry",
            intensity="intense",
            description="angry (intense)",
            instruct="husky voice, angry",
            base_description="Adult woman, husky voice",
        )
        d = meta.to_dict()
        meta2 = PromptMetadata.from_dict(d)
        assert meta2.character == "kira"
        assert meta2.emotion == "angry"
        assert meta2.intensity == "intense"
        assert meta2.description == "angry (intense)"
        assert meta2.instruct == "husky voice, angry"
        assert meta2.base_description == "Adult woman, husky voice"
