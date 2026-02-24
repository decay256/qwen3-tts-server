"""Persistent storage for voice clone prompts.

Stores serialized VoiceClonePromptItem data (torch tensors) alongside
JSON metadata sidecars. Provides LRU caching for frequently-used prompts.
"""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy torch import — only needed when actually saving/loading prompts
_torch = None


def _get_torch():
    global _torch
    if _torch is None:
        import torch
        _torch = torch
    return _torch


@dataclass
class PromptMetadata:
    """Metadata for a saved clone prompt."""
    name: str
    tags: list[str] = field(default_factory=list)
    ref_text: Optional[str] = None
    created_at: Optional[str] = None
    ref_audio_duration_s: Optional[float] = None
    x_vector_only_mode: bool = False
    icl_mode: bool = True

    def matches_tags(self, query_tags: list[str]) -> bool:
        """Check if this prompt has ALL the requested tags (AND logic)."""
        return all(t in self.tags for t in query_tags)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tags": self.tags,
            "ref_text": self.ref_text,
            "created_at": self.created_at,
            "ref_audio_duration_s": self.ref_audio_duration_s,
            "x_vector_only_mode": self.x_vector_only_mode,
            "icl_mode": self.icl_mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PromptMetadata:
        return cls(
            name=data["name"],
            tags=data.get("tags", []),
            ref_text=data.get("ref_text"),
            created_at=data.get("created_at"),
            ref_audio_duration_s=data.get("ref_audio_duration_s"),
            x_vector_only_mode=data.get("x_vector_only_mode", False),
            icl_mode=data.get("icl_mode", True),
        )


class PromptStore:
    """Manages persistent storage and caching of voice clone prompts.

    Directory layout::

        voice-prompts/
        ├── {name}.prompt    # torch.save({'ref_code': ..., 'ref_spk_embedding': ..., ...})
        ├── {name}.json      # metadata sidecar
        └── ...
    """

    def __init__(self, prompts_dir: str | Path, cache_size: int = 32) -> None:
        self.prompts_dir = Path(prompts_dir)
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        self._cache_size = cache_size
        self._cache: OrderedDict[str, object] = OrderedDict()  # name → VoiceClonePromptItem
        self._metadata: dict[str, PromptMetadata] = {}
        self._load_metadata_index()

    def _load_metadata_index(self) -> None:
        """Scan directory and load all metadata sidecars into memory."""
        for json_path in self.prompts_dir.glob("*.json"):
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                meta = PromptMetadata.from_dict(data)
                self._metadata[meta.name] = meta
            except Exception:
                logger.warning("Failed to load metadata: %s", json_path, exc_info=True)
        logger.info("Prompt store loaded %d metadata entries from %s", len(self._metadata), self.prompts_dir)

    def save_prompt(
        self,
        name: str,
        prompt_item: object,  # VoiceClonePromptItem
        tags: list[str] | None = None,
        ref_text: str | None = None,
        ref_audio_duration_s: float | None = None,
    ) -> PromptMetadata:
        """Save a clone prompt to disk.

        Args:
            name: Unique name for this prompt (used as filename).
            prompt_item: VoiceClonePromptItem from create_voice_clone_prompt().
            tags: Optional tags for filtering.
            ref_text: Transcript of the reference audio.
            ref_audio_duration_s: Duration of reference audio in seconds.

        Returns:
            PromptMetadata for the saved prompt.

        Raises:
            ValueError: If name contains invalid characters.
        """
        # Validate name (filesystem-safe)
        if not name or not all(c.isalnum() or c in "-_" for c in name):
            raise ValueError(f"Invalid prompt name: {name!r} (use alphanumeric, hyphens, underscores)")

        torch = _get_torch()

        # Serialize tensors
        prompt_path = self.prompts_dir / f"{name}.prompt"
        tensor_data = {
            "ref_code": prompt_item.ref_code,
            "ref_spk_embedding": prompt_item.ref_spk_embedding,
            "x_vector_only_mode": prompt_item.x_vector_only_mode,
            "icl_mode": prompt_item.icl_mode,
            "ref_text": prompt_item.ref_text,
        }
        torch.save(tensor_data, prompt_path)

        # Save metadata
        from datetime import datetime, timezone
        meta = PromptMetadata(
            name=name,
            tags=tags or [],
            ref_text=ref_text or prompt_item.ref_text,
            created_at=datetime.now(timezone.utc).isoformat(),
            ref_audio_duration_s=ref_audio_duration_s,
            x_vector_only_mode=prompt_item.x_vector_only_mode,
            icl_mode=prompt_item.icl_mode,
        )
        json_path = self.prompts_dir / f"{name}.json"
        json_path.write_text(json.dumps(meta.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

        self._metadata[name] = meta

        # Update cache
        self._cache[name] = prompt_item
        self._evict_cache()

        logger.info("Saved clone prompt '%s' (tags=%s)", name, tags)
        return meta

    def load_prompt(self, name: str, device: str = "cpu") -> object:
        """Load a clone prompt by name.

        Returns cached version if available, otherwise loads from disk.

        Args:
            name: Prompt name.
            device: Torch device to load tensors to.

        Returns:
            VoiceClonePromptItem (or equivalent dataclass).

        Raises:
            FileNotFoundError: If prompt doesn't exist.
        """
        # Check cache
        if name in self._cache:
            self._cache.move_to_end(name)
            return self._cache[name]

        # Load from disk
        prompt_path = self.prompts_dir / f"{name}.prompt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Clone prompt not found: {name}")

        torch = _get_torch()
        data = torch.load(prompt_path, map_location=device, weights_only=False)

        # Reconstruct VoiceClonePromptItem
        from qwen_tts import VoiceClonePromptItem
        prompt_item = VoiceClonePromptItem(
            ref_code=data["ref_code"],
            ref_spk_embedding=data["ref_spk_embedding"],
            x_vector_only_mode=data["x_vector_only_mode"],
            icl_mode=data["icl_mode"],
            ref_text=data.get("ref_text"),
        )

        # Cache it
        self._cache[name] = prompt_item
        self._evict_cache()

        logger.debug("Loaded clone prompt '%s' from disk", name)
        return prompt_item

    def list_prompts(self, tags: list[str] | None = None) -> list[dict]:
        """List all saved prompts, optionally filtered by tags.

        Args:
            tags: If provided, only return prompts matching ALL tags.

        Returns:
            List of metadata dicts.
        """
        results = []
        for meta in self._metadata.values():
            if tags and not meta.matches_tags(tags):
                continue
            results.append(meta.to_dict())
        return sorted(results, key=lambda x: x["name"])

    def delete_prompt(self, name: str) -> bool:
        """Delete a saved prompt.

        Args:
            name: Prompt name.

        Returns:
            True if deleted, False if not found.
        """
        prompt_path = self.prompts_dir / f"{name}.prompt"
        json_path = self.prompts_dir / f"{name}.json"

        if name not in self._metadata and not prompt_path.exists():
            return False

        prompt_path.unlink(missing_ok=True)
        json_path.unlink(missing_ok=True)
        self._metadata.pop(name, None)
        self._cache.pop(name, None)

        logger.info("Deleted clone prompt '%s'", name)
        return True

    def get_metadata(self, name: str) -> PromptMetadata | None:
        """Get metadata for a prompt without loading tensors."""
        return self._metadata.get(name)

    def _evict_cache(self) -> None:
        """Evict oldest entries if cache exceeds max size."""
        while len(self._cache) > self._cache_size:
            evicted_name, _ = self._cache.popitem(last=False)
            logger.debug("Evicted prompt '%s' from cache", evicted_name)
