"""Tests for GCS prompt sync layer.

All tests mock the GCS client — no real GCS calls are made.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_mock_blob(name: str, size: int = 1024, exists: bool = True, metadata: dict = None):
    """Create a mock GCS Blob."""
    blob = MagicMock()
    blob.name = name
    blob.size = size
    blob.etag = "abc123"
    blob.metadata = metadata or {}
    blob.exists.return_value = exists
    blob.time_created = MagicMock()
    blob.time_created.isoformat.return_value = "2026-01-01T00:00:00+00:00"
    blob.updated = MagicMock()
    blob.updated.isoformat.return_value = "2026-01-01T01:00:00+00:00"
    return blob


def _make_gcs_store(tmp_path, mock_client=None):
    """Create a GCSPromptStore with a mocked GCS client."""
    if mock_client is None:
        mock_client = MagicMock()
        mock_client.bucket.return_value = MagicMock()

    with patch("server.prompt_sync.GCSPromptStore._build_client", return_value=mock_client):
        from server.prompt_sync import GCSPromptStore
        store = GCSPromptStore(
            bucket="test-bucket",
            prefix="voice-prompts/",
            cache_dir=str(tmp_path / "cache"),
        )
        store._client = mock_client
        store._bucket = mock_client.bucket.return_value
        return store


# ── PromptGCSMetadata ────────────────────────────────────────────────────────


class TestPromptGCSMetadata:
    def test_to_gcs_meta_all_fields(self):
        from server.prompt_sync import PromptGCSMetadata
        meta = PromptGCSMetadata(
            character="maya",
            description="calm voice",
            tags=["calm", "female"],
            source_backend="tunnel-01",
            source_backend_type="tunnel",
            ref_text="Hello world",
            x_vector_only=True,
            created_at="2026-01-01T00:00:00Z",
        )
        gcs = meta.to_gcs_meta()
        assert gcs["qwen3_character"] == "maya"
        assert gcs["qwen3_description"] == "calm voice"
        assert json.loads(gcs["qwen3_tags"]) == ["calm", "female"]
        assert gcs["qwen3_source_backend"] == "tunnel-01"
        assert gcs["qwen3_source_backend_type"] == "tunnel"
        assert gcs["qwen3_ref_text"] == "Hello world"
        assert gcs["qwen3_x_vector_only"] == "true"
        assert gcs["qwen3_created_at"] == "2026-01-01T00:00:00Z"

    def test_to_gcs_meta_minimal(self):
        from server.prompt_sync import PromptGCSMetadata
        meta = PromptGCSMetadata()
        gcs = meta.to_gcs_meta()
        # Only x_vector_only is always emitted
        assert gcs["qwen3_x_vector_only"] == "false"
        assert "qwen3_character" not in gcs

    def test_from_gcs_meta_roundtrip(self):
        from server.prompt_sync import PromptGCSMetadata
        original = PromptGCSMetadata(
            character="narrator",
            tags=["deep", "male"],
            source_backend_type="runpod",
            x_vector_only=False,
            created_at="2026-02-01T10:00:00Z",
        )
        roundtripped = PromptGCSMetadata.from_gcs_meta(original.to_gcs_meta())
        assert roundtripped.character == original.character
        assert roundtripped.tags == original.tags
        assert roundtripped.source_backend_type == original.source_backend_type
        assert roundtripped.x_vector_only == original.x_vector_only

    def test_from_gcs_meta_empty(self):
        from server.prompt_sync import PromptGCSMetadata
        meta = PromptGCSMetadata.from_gcs_meta({})
        assert meta.character is None
        assert meta.tags == []
        assert meta.x_vector_only is False

    def test_from_gcs_meta_malformed_tags(self):
        from server.prompt_sync import PromptGCSMetadata
        meta = PromptGCSMetadata.from_gcs_meta({"qwen3_tags": "not-valid-json"})
        assert meta.tags == []


# ── GCSPromptStore helper functions ──────────────────────────────────────────


class TestGCSObjectName:
    def test_basic_id(self):
        from server.prompt_sync import _gcs_object_name
        assert _gcs_object_name("maya-calm") == "voice-prompts/maya-calm.pt"

    def test_strips_pt_suffix(self):
        from server.prompt_sync import _gcs_object_name
        assert _gcs_object_name("maya-calm.pt") == "voice-prompts/maya-calm.pt"

    def test_id_with_slash(self):
        from server.prompt_sync import _gcs_object_name
        assert _gcs_object_name("deep-echoes/chen") == "voice-prompts/deep-echoes/chen.pt"


# ── GCSPromptStore.push ───────────────────────────────────────────────────────


class TestGCSPromptStorePush:
    def test_push_uploads_file(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        # Create a real local .pt file
        pt_file = tmp_path / "maya-calm.pt"
        pt_file.write_bytes(b"\x00" * 512)

        mock_blob = _make_mock_blob("voice-prompts/maya-calm.pt", size=512)
        store._bucket.blob.return_value = mock_blob

        from server.prompt_sync import PushResult
        result = store.push("maya-calm", str(pt_file))

        mock_blob.upload_from_filename.assert_called_once_with(str(pt_file))
        assert isinstance(result, PushResult)
        assert result.prompt_id == "maya-calm"
        assert result.gcs_path == "gs://test-bucket/voice-prompts/maya-calm.pt"
        assert result.size_bytes == 512
        assert result.status == "uploaded"
        assert result.etag == "abc123"

    def test_push_with_metadata(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        pt_file = tmp_path / "maya-calm.pt"
        pt_file.write_bytes(b"fake-tensor-data")

        mock_blob = _make_mock_blob("voice-prompts/maya-calm.pt")
        store._bucket.blob.return_value = mock_blob

        from server.prompt_sync import PromptGCSMetadata
        meta = PromptGCSMetadata(character="maya", tags=["calm"])
        store.push("maya-calm", str(pt_file), metadata=meta)

        # Metadata should be set on the blob before upload
        assert mock_blob.metadata is not None
        assert "qwen3_character" in mock_blob.metadata

    def test_push_missing_local_file_raises(self, tmp_path):
        store = _make_gcs_store(tmp_path)
        with pytest.raises(FileNotFoundError, match="not found"):
            store.push("maya-calm", "/nonexistent/path/maya.pt")

    def test_push_strips_pt_suffix_from_id(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        pt_file = tmp_path / "maya.pt"
        pt_file.write_bytes(b"data")

        mock_blob = _make_mock_blob("voice-prompts/maya.pt")
        store._bucket.blob.return_value = mock_blob

        result = store.push("maya.pt", str(pt_file))
        # Object name should not double the .pt
        store._bucket.blob.assert_called_with("voice-prompts/maya.pt")

    def test_push_upload_failure_raises(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        pt_file = tmp_path / "bad.pt"
        pt_file.write_bytes(b"data")

        mock_blob = _make_mock_blob("voice-prompts/bad.pt")
        mock_blob.upload_from_filename.side_effect = Exception("network error")
        store._bucket.blob.return_value = mock_blob

        with pytest.raises(RuntimeError, match="GCS upload failed"):
            store.push("bad", str(pt_file))


# ── GCSPromptStore.pull ───────────────────────────────────────────────────────


class TestGCSPromptStorePull:
    def test_pull_downloads_file(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        target_dir = tmp_path / "voices"
        mock_blob = _make_mock_blob("voice-prompts/maya-calm.pt", size=768)
        mock_blob.exists.return_value = True

        # Simulate download writing a file
        def fake_download(path):
            Path(path).write_bytes(b"\x00" * 768)

        mock_blob.download_to_filename.side_effect = fake_download
        store._bucket.blob.return_value = mock_blob

        from server.prompt_sync import PullResult
        result = store.pull("maya-calm", str(target_dir))

        mock_blob.download_to_filename.assert_called_once()
        assert isinstance(result, PullResult)
        assert result.prompt_id == "maya-calm"
        assert result.status == "downloaded"
        assert result.local_path.endswith("maya-calm.pt")
        assert result.size_bytes == 768

    def test_pull_cache_hit_skips_download(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        target_dir = tmp_path / "voices"
        target_dir.mkdir()
        cached = target_dir / "maya-calm.pt"
        cached.write_bytes(b"cached")

        mock_blob = _make_mock_blob("voice-prompts/maya-calm.pt")
        store._bucket.blob.return_value = mock_blob

        result = store.pull("maya-calm", str(target_dir))

        mock_blob.download_to_filename.assert_not_called()
        assert result.status == "already_cached"

    def test_pull_force_overwrites_cache(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        target_dir = tmp_path / "voices"
        target_dir.mkdir()
        cached = target_dir / "maya-calm.pt"
        cached.write_bytes(b"old-data")

        mock_blob = _make_mock_blob("voice-prompts/maya-calm.pt", size=256)
        mock_blob.exists.return_value = True

        def fake_download(path):
            Path(path).write_bytes(b"\xff" * 256)

        mock_blob.download_to_filename.side_effect = fake_download
        store._bucket.blob.return_value = mock_blob

        result = store.pull("maya-calm", str(target_dir), force=True)

        mock_blob.download_to_filename.assert_called_once()
        assert result.status == "downloaded"

    def test_pull_not_in_gcs_raises(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        mock_blob = _make_mock_blob("voice-prompts/missing.pt", exists=False)
        store._bucket.blob.return_value = mock_blob

        with pytest.raises(FileNotFoundError, match="missing"):
            store.pull("missing", str(tmp_path / "voices"))

    def test_pull_creates_target_dir(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        target_dir = tmp_path / "new" / "nested" / "dir"
        assert not target_dir.exists()

        mock_blob = _make_mock_blob("voice-prompts/maya.pt", size=100)
        mock_blob.exists.return_value = True

        def fake_download(path):
            Path(path).write_bytes(b"x" * 100)

        mock_blob.download_to_filename.side_effect = fake_download
        store._bucket.blob.return_value = mock_blob

        store.pull("maya", str(target_dir))
        assert target_dir.exists()


# ── GCSPromptStore.ensure_local ───────────────────────────────────────────────


class TestGCSPromptStoreEnsureLocal:
    def test_ensure_local_cache_hit(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        cached = voices_dir / "maya-calm.pt"
        cached.write_bytes(b"data")

        from server.prompt_sync import EnsureLocalResult
        result = store.ensure_local("maya-calm", str(voices_dir))

        assert isinstance(result, EnsureLocalResult)
        assert result.cache_hit is True
        assert result.prompt_id == "maya-calm"
        assert result.local_path.endswith("maya-calm.pt")
        # No GCS calls on cache hit
        store._bucket.blob.assert_not_called()

    def test_ensure_local_cache_miss_triggers_pull(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        voices_dir = tmp_path / "voices"

        mock_blob = _make_mock_blob("voice-prompts/maya-calm.pt", size=512)
        mock_blob.exists.return_value = True

        def fake_download(path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"x" * 512)

        mock_blob.download_to_filename.side_effect = fake_download
        store._bucket.blob.return_value = mock_blob

        result = store.ensure_local("maya-calm", str(voices_dir))

        assert result.cache_hit is False
        assert result.size_bytes == 512
        mock_blob.download_to_filename.assert_called_once()

    def test_ensure_local_normalizes_pt_suffix(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        cached = voices_dir / "maya.pt"
        cached.write_bytes(b"data")

        # prompt_id with .pt suffix — should still find it
        result = store.ensure_local("maya.pt", str(voices_dir))
        assert result.cache_hit is True


# ── GCSPromptStore.list ───────────────────────────────────────────────────────


class TestGCSPromptStoreList:
    def test_list_returns_records(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        blobs = [
            _make_mock_blob("voice-prompts/maya-calm.pt", size=512),
            _make_mock_blob("voice-prompts/narrator-neutral.pt", size=1024),
        ]
        store._client.list_blobs.return_value = iter(blobs)

        records = store.list()

        assert len(records) == 2
        ids = {r.prompt_id for r in records}
        assert "maya-calm" in ids
        assert "narrator-neutral" in ids

    def test_list_empty_bucket(self, tmp_path):
        store = _make_gcs_store(tmp_path)
        store._client.list_blobs.return_value = iter([])

        records = store.list()
        assert records == []

    def test_list_sorted_by_prompt_id(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        blobs = [
            _make_mock_blob("voice-prompts/zzz.pt"),
            _make_mock_blob("voice-prompts/aaa.pt"),
            _make_mock_blob("voice-prompts/mmm.pt"),
        ]
        store._client.list_blobs.return_value = iter(blobs)

        records = store.list()
        ids = [r.prompt_id for r in records]
        assert ids == sorted(ids)

    def test_list_marks_local_cached(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        # Write a local cache file
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "maya-calm.pt").write_bytes(b"cached")
        store._cache_dir = cache_dir

        blobs = [
            _make_mock_blob("voice-prompts/maya-calm.pt"),
            _make_mock_blob("voice-prompts/narrator.pt"),
        ]
        store._client.list_blobs.return_value = iter(blobs)

        records = store.list()
        by_id = {r.prompt_id: r for r in records}
        assert by_id["maya-calm"].local_cached is True
        assert by_id["narrator"].local_cached is False

    def test_list_skips_prefix_only_blob(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        # A blob with name exactly equal to the prefix (directory-like)
        blobs = [
            _make_mock_blob("voice-prompts/"),  # prefix blob — no prompt_id
            _make_mock_blob("voice-prompts/maya.pt"),
        ]
        store._client.list_blobs.return_value = iter(blobs)

        records = store.list()
        assert len(records) == 1
        assert records[0].prompt_id == "maya"


# ── GCSPromptStore.delete ─────────────────────────────────────────────────────


class TestGCSPromptStoreDelete:
    def test_delete_removes_gcs_and_local(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        # Create local cache file
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        local = cache_dir / "maya.pt"
        local.write_bytes(b"data")
        store._cache_dir = cache_dir

        mock_blob = _make_mock_blob("voice-prompts/maya.pt")
        mock_blob.exists.return_value = True
        store._bucket.blob.return_value = mock_blob

        from server.prompt_sync import DeleteResult
        result = store.delete("maya", delete_local=True)

        assert isinstance(result, DeleteResult)
        assert result.gcs_deleted is True
        assert result.local_deleted is True
        assert not local.exists()
        mock_blob.delete.assert_called_once()

    def test_delete_gcs_only(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        local = cache_dir / "maya.pt"
        local.write_bytes(b"data")
        store._cache_dir = cache_dir

        mock_blob = _make_mock_blob("voice-prompts/maya.pt")
        mock_blob.exists.return_value = True
        store._bucket.blob.return_value = mock_blob

        result = store.delete("maya", delete_local=False)

        assert result.gcs_deleted is True
        assert result.local_deleted is False
        assert local.exists()  # not deleted

    def test_delete_not_in_gcs(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        mock_blob = _make_mock_blob("voice-prompts/missing.pt", exists=False)
        store._bucket.blob.return_value = mock_blob

        result = store.delete("missing")
        assert result.gcs_deleted is False
        mock_blob.delete.assert_not_called()

    def test_delete_no_local_file(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        mock_blob = _make_mock_blob("voice-prompts/maya.pt")
        mock_blob.exists.return_value = True
        store._bucket.blob.return_value = mock_blob

        # No local file exists; delete_local=True should not crash
        result = store.delete("maya", delete_local=True)
        assert result.local_deleted is False


# ── GCSPromptStore.exists ─────────────────────────────────────────────────────


class TestGCSPromptStoreExists:
    def test_exists_true(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        mock_blob = _make_mock_blob("voice-prompts/maya.pt", size=1024)
        mock_blob.exists.return_value = True
        store._bucket.blob.return_value = mock_blob

        from server.prompt_sync import ExistsResult
        result = store.exists("maya")

        assert isinstance(result, ExistsResult)
        assert result.exists is True
        assert result.prompt_id == "maya"
        assert result.gcs_path == "gs://test-bucket/voice-prompts/maya.pt"
        assert result.size_bytes == 1024

    def test_exists_false(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        mock_blob = _make_mock_blob("voice-prompts/missing.pt", exists=False)
        store._bucket.blob.return_value = mock_blob

        result = store.exists("missing")

        assert result.exists is False
        assert result.gcs_path is None
        assert result.size_bytes is None

    def test_exists_normalizes_pt_suffix(self, tmp_path):
        store = _make_gcs_store(tmp_path)

        mock_blob = _make_mock_blob("voice-prompts/maya.pt", exists=True)
        store._bucket.blob.return_value = mock_blob

        # With .pt suffix — should still work
        result = store.exists("maya.pt")
        store._bucket.blob.assert_called_with("voice-prompts/maya.pt")
