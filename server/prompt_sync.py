"""GCS-backed voice prompt sync layer.

Uploads voice clone prompt (.pt) files to Google Cloud Storage so that
any GPU backend (RunPod, Lambda, etc.) can retrieve them without requiring
the local tunnel to be connected.

Storage layout:
    gs://eigen-backups-dkev/voice-prompts/{prompt_id}.pt

Local cache:
    ~/.cache/qwen3-tts/voice-prompts/{prompt_id}.pt
    (configurable via QWEN3_PROMPT_CACHE_DIR env var)

Credentials:
    .secrets/gcloud-service-account.json  (droplet)
    or GOOGLE_APPLICATION_CREDENTIALS env var (standard SDK fallback)
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

GCS_BUCKET = "eigen-backups-dkev"
GCS_PREFIX = "voice-prompts/"
DEFAULT_KEY_FILE = ".secrets/gcloud-service-account.json"
DEFAULT_CACHE_DIR = os.path.expanduser("~/.cache/qwen3-tts/voice-prompts")


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class PromptGCSMetadata:
    """Optional metadata stored alongside a GCS object."""
    character: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    source_backend: Optional[str] = None
    source_backend_type: Optional[str] = None
    ref_text: Optional[str] = None
    x_vector_only: bool = False
    created_at: Optional[str] = None

    def to_gcs_meta(self) -> dict[str, str]:
        """Convert to GCS object custom metadata (all values must be strings)."""
        meta: dict[str, str] = {}
        if self.character:
            meta["qwen3_character"] = self.character
        if self.description:
            meta["qwen3_description"] = self.description
        if self.tags:
            meta["qwen3_tags"] = json.dumps(self.tags)
        if self.source_backend:
            meta["qwen3_source_backend"] = self.source_backend
        if self.source_backend_type:
            meta["qwen3_source_backend_type"] = self.source_backend_type
        if self.ref_text:
            meta["qwen3_ref_text"] = self.ref_text
        meta["qwen3_x_vector_only"] = str(self.x_vector_only).lower()
        if self.created_at:
            meta["qwen3_created_at"] = self.created_at
        return meta

    @classmethod
    def from_gcs_meta(cls, raw: dict[str, str]) -> "PromptGCSMetadata":
        """Reconstruct from GCS object custom metadata."""
        tags_raw = raw.get("qwen3_tags", "[]")
        try:
            tags = json.loads(tags_raw)
        except (json.JSONDecodeError, TypeError):
            tags = []
        return cls(
            character=raw.get("qwen3_character"),
            description=raw.get("qwen3_description"),
            tags=tags,
            source_backend=raw.get("qwen3_source_backend"),
            source_backend_type=raw.get("qwen3_source_backend_type"),
            ref_text=raw.get("qwen3_ref_text"),
            x_vector_only=raw.get("qwen3_x_vector_only", "false").lower() == "true",
            created_at=raw.get("qwen3_created_at"),
        )


@dataclass
class PushResult:
    prompt_id: str
    gcs_path: str
    size_bytes: int
    status: str  # "uploaded" | "already_exists"
    etag: Optional[str] = None


@dataclass
class PullResult:
    prompt_id: str
    local_path: str
    size_bytes: int
    status: str  # "downloaded" | "already_cached"
    source: str = "gcs"


@dataclass
class EnsureLocalResult:
    prompt_id: str
    local_path: str
    cache_hit: bool
    size_bytes: int


@dataclass
class PromptRecord:
    prompt_id: str
    gcs_path: str
    size_bytes: int
    created_at: str
    updated_at: str
    metadata: PromptGCSMetadata
    local_cached: bool


@dataclass
class DeleteResult:
    prompt_id: str
    gcs_deleted: bool
    local_deleted: bool


@dataclass
class ExistsResult:
    prompt_id: str
    exists: bool
    gcs_path: Optional[str] = None
    size_bytes: Optional[int] = None


@dataclass
class SignedUrlResult:
    prompt_id: str
    url: str
    expires_at: str
    method: str


# ── Abstract interface ────────────────────────────────────────────────────────

class PromptSyncProvider(ABC):
    """Abstract interface for voice prompt cloud sync."""

    @abstractmethod
    def push(
        self,
        prompt_id: str,
        local_path: str,
        metadata: Optional[PromptGCSMetadata] = None,
    ) -> PushResult:
        """Upload a .pt file to cloud storage."""
        ...

    @abstractmethod
    def pull(
        self,
        prompt_id: str,
        local_dir: str,
        force: bool = False,
    ) -> PullResult:
        """Download a .pt file from cloud storage to local_dir."""
        ...

    @abstractmethod
    def ensure_local(
        self,
        prompt_id: str,
        local_dir: str,
    ) -> EnsureLocalResult:
        """Guarantee the prompt is in local_dir; pull from GCS if not.

        Fast path: stat check only if file already exists.
        """
        ...

    @abstractmethod
    def list(self) -> list[PromptRecord]:
        """List all prompt IDs stored in cloud."""
        ...

    @abstractmethod
    def delete(self, prompt_id: str, delete_local: bool = True) -> DeleteResult:
        """Delete from cloud (and optionally local cache)."""
        ...

    @abstractmethod
    def exists(self, prompt_id: str) -> ExistsResult:
        """Check if prompt exists in cloud without downloading."""
        ...

    def get_signed_url(
        self,
        prompt_id: str,
        ttl_seconds: int = 3600,
        method: str = "GET",
    ) -> SignedUrlResult:
        """Generate a short-lived signed URL for the prompt file.

        Default implementation raises NotImplementedError — override in GCS impl.
        """
        raise NotImplementedError("Signed URLs not supported by this provider")


# ── GCS implementation ────────────────────────────────────────────────────────

def _normalize_prompt_id(prompt_id: str) -> str:
    """Strip .pt suffix if present so storage is always consistent."""
    if prompt_id.endswith(".pt"):
        return prompt_id[:-3]
    return prompt_id


def _gcs_object_name(prompt_id: str) -> str:
    """Build the full GCS object name from a prompt_id.

    Example: "maya-calm" → "voice-prompts/maya-calm.pt"
    """
    return f"{GCS_PREFIX}{_normalize_prompt_id(prompt_id)}.pt"


def _gcs_path(object_name: str, bucket: str = GCS_BUCKET) -> str:
    return f"gs://{bucket}/{object_name}"


class GCSPromptStore(PromptSyncProvider):
    """Google Cloud Storage implementation of PromptSyncProvider.

    Credentials are loaded (in order):
    1. Explicit key_file parameter
    2. .secrets/gcloud-service-account.json (relative to CWD)
    3. GOOGLE_APPLICATION_CREDENTIALS environment variable (standard SDK)
    """

    def __init__(
        self,
        bucket: str = GCS_BUCKET,
        prefix: str = GCS_PREFIX,
        key_file: Optional[str] = None,
        cache_dir: Optional[str] = None,
    ) -> None:
        self._bucket_name = bucket
        self._prefix = prefix
        self._cache_dir = Path(cache_dir or os.environ.get("QWEN3_PROMPT_CACHE_DIR", DEFAULT_CACHE_DIR))

        # Resolve credentials
        self._client = self._build_client(key_file)
        self._bucket = self._client.bucket(self._bucket_name)

        logger.info(
            "GCSPromptStore initialized: bucket=%s, prefix=%s, cache=%s",
            self._bucket_name, self._prefix, self._cache_dir,
        )

    def _build_client(self, key_file: Optional[str]):
        """Build a GCS client using the best available credentials."""
        from google.cloud import storage
        from google.oauth2 import service_account

        # Explicit key_file > default location > SDK auto-detect
        candidates = []
        if key_file:
            candidates.append(key_file)
        candidates.append(DEFAULT_KEY_FILE)

        for candidate in candidates:
            path = Path(candidate)
            if path.exists():
                logger.info("GCSPromptStore: using service account key at %s", path)
                creds = service_account.Credentials.from_service_account_file(
                    str(path),
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                return storage.Client(credentials=creds, project=creds.project_id)

        # Fall back to Application Default Credentials
        logger.info("GCSPromptStore: no key file found, using Application Default Credentials")
        return storage.Client()

    def _local_path(self, prompt_id: str) -> Path:
        """Return the expected local cache path for a prompt."""
        clean_id = _normalize_prompt_id(prompt_id)
        return self._cache_dir / f"{clean_id}.pt"

    def _ensure_cache_dir(self) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def push(
        self,
        prompt_id: str,
        local_path: str,
        metadata: Optional[PromptGCSMetadata] = None,
    ) -> PushResult:
        """Upload a .pt file to GCS.

        Args:
            prompt_id: Unique prompt identifier (with or without .pt suffix).
            local_path: Absolute path to the .pt file.
            metadata: Optional GCS object metadata to attach.

        Returns:
            PushResult with GCS path, size, status.

        Raises:
            FileNotFoundError: If local_path doesn't exist.
            RuntimeError: If upload fails.
        """
        local = Path(local_path)
        if not local.exists():
            raise FileNotFoundError(f"Prompt file not found: {local_path}")

        object_name = _gcs_object_name(prompt_id)
        blob = self._bucket.blob(object_name)

        if metadata:
            blob.metadata = metadata.to_gcs_meta()

        logger.info("GCS push: %s → %s", local_path, _gcs_path(object_name, self._bucket_name))
        try:
            blob.upload_from_filename(str(local))
        except Exception as exc:
            raise RuntimeError(f"GCS upload failed for {prompt_id}: {exc}") from exc

        blob.reload()  # refresh etag + size
        size = blob.size or local.stat().st_size

        return PushResult(
            prompt_id=prompt_id,
            gcs_path=_gcs_path(object_name, self._bucket_name),
            size_bytes=size,
            status="uploaded",
            etag=blob.etag,
        )

    def pull(
        self,
        prompt_id: str,
        local_dir: str,
        force: bool = False,
    ) -> PullResult:
        """Download a .pt file from GCS into local_dir.

        Args:
            prompt_id: Unique prompt identifier.
            local_dir: Directory to download into.
            force: If True, re-download even if local file already exists.

        Returns:
            PullResult with local path and status.

        Raises:
            FileNotFoundError: If prompt doesn't exist in GCS.
            RuntimeError: If download fails.
        """
        local_directory = Path(local_dir)
        local_directory.mkdir(parents=True, exist_ok=True)

        clean_id = _normalize_prompt_id(prompt_id)
        local = local_directory / f"{clean_id}.pt"

        if not force and local.exists():
            return PullResult(
                prompt_id=prompt_id,
                local_path=str(local),
                size_bytes=local.stat().st_size,
                status="already_cached",
            )

        object_name = _gcs_object_name(prompt_id)
        blob = self._bucket.blob(object_name)

        if not blob.exists():
            raise FileNotFoundError(f"Prompt '{prompt_id}' not found in GCS")

        logger.info("GCS pull: %s → %s", _gcs_path(object_name, self._bucket_name), local)
        try:
            blob.download_to_filename(str(local))
        except Exception as exc:
            raise RuntimeError(f"GCS download failed for {prompt_id}: {exc}") from exc

        return PullResult(
            prompt_id=prompt_id,
            local_path=str(local),
            size_bytes=local.stat().st_size,
            status="downloaded",
        )

    def ensure_local(
        self,
        prompt_id: str,
        local_dir: str,
    ) -> EnsureLocalResult:
        """Ensure the prompt .pt file is present in local_dir.

        Cache-hit fast path: only does a stat() check, no GCS calls.

        Args:
            prompt_id: Unique prompt identifier.
            local_dir: Directory to check / download into.

        Returns:
            EnsureLocalResult with local path and cache_hit flag.
        """
        local_directory = Path(local_dir)
        clean_id = _normalize_prompt_id(prompt_id)
        local = local_directory / f"{clean_id}.pt"

        if local.exists():
            logger.debug("GCS ensure_local cache hit: %s", local)
            return EnsureLocalResult(
                prompt_id=prompt_id,
                local_path=str(local),
                cache_hit=True,
                size_bytes=local.stat().st_size,
            )

        logger.info("GCS ensure_local cache miss, pulling: %s", prompt_id)
        pull_result = self.pull(prompt_id, local_dir)
        return EnsureLocalResult(
            prompt_id=prompt_id,
            local_path=pull_result.local_path,
            cache_hit=False,
            size_bytes=pull_result.size_bytes,
        )

    def list(self) -> list[PromptRecord]:
        """List all prompts stored in GCS under the prefix.

        Returns:
            List of PromptRecord objects sorted by prompt_id.
        """
        records = []
        blobs = self._client.list_blobs(self._bucket_name, prefix=self._prefix)

        for blob in blobs:
            # Strip prefix and .pt suffix to get the prompt_id
            name = blob.name  # e.g. "voice-prompts/maya-calm.pt"
            if not name.startswith(self._prefix):
                continue
            relative = name[len(self._prefix):]  # "maya-calm.pt"
            if not relative:
                continue

            prompt_id = relative[:-3] if relative.endswith(".pt") else relative
            gcs_path = _gcs_path(name, self._bucket_name)

            # Check local cache
            clean_id = _normalize_prompt_id(prompt_id)
            local = self._cache_dir / f"{clean_id}.pt"

            meta = PromptGCSMetadata.from_gcs_meta(blob.metadata or {})
            created_at = blob.time_created.isoformat() if blob.time_created else ""
            updated_at = blob.updated.isoformat() if blob.updated else ""

            records.append(PromptRecord(
                prompt_id=prompt_id,
                gcs_path=gcs_path,
                size_bytes=blob.size or 0,
                created_at=created_at,
                updated_at=updated_at,
                metadata=meta,
                local_cached=local.exists(),
            ))

        return sorted(records, key=lambda r: r.prompt_id)

    def delete(self, prompt_id: str, delete_local: bool = True) -> DeleteResult:
        """Delete a prompt from GCS and optionally from local cache.

        Args:
            prompt_id: Unique prompt identifier.
            delete_local: If True, also remove local cache file.

        Returns:
            DeleteResult.
        """
        object_name = _gcs_object_name(prompt_id)
        blob = self._bucket.blob(object_name)

        gcs_deleted = False
        if blob.exists():
            blob.delete()
            gcs_deleted = True
            logger.info("GCS delete: %s", _gcs_path(object_name, self._bucket_name))
        else:
            logger.warning("GCS delete: prompt '%s' not found in GCS", prompt_id)

        local_deleted = False
        if delete_local:
            local = self._local_path(prompt_id)
            if local.exists():
                local.unlink()
                local_deleted = True
                logger.info("Local delete: %s", local)

        return DeleteResult(
            prompt_id=prompt_id,
            gcs_deleted=gcs_deleted,
            local_deleted=local_deleted,
        )

    def exists(self, prompt_id: str) -> ExistsResult:
        """Check if a prompt exists in GCS without downloading.

        Args:
            prompt_id: Unique prompt identifier.

        Returns:
            ExistsResult.
        """
        object_name = _gcs_object_name(prompt_id)
        blob = self._bucket.blob(object_name)

        if not blob.exists():
            return ExistsResult(prompt_id=prompt_id, exists=False)

        blob.reload()
        return ExistsResult(
            prompt_id=prompt_id,
            exists=True,
            gcs_path=_gcs_path(object_name, self._bucket_name),
            size_bytes=blob.size,
        )

    def get_signed_url(
        self,
        prompt_id: str,
        ttl_seconds: int = 3600,
        method: str = "GET",
    ) -> SignedUrlResult:
        """Generate a short-lived HTTPS signed URL for the prompt file.

        Used when a stateless backend (RunPod) needs to download the prompt
        without holding GCS credentials.

        Args:
            prompt_id: Unique prompt identifier.
            ttl_seconds: URL lifetime in seconds (default 1 hour).
            method: "GET" or "PUT".

        Returns:
            SignedUrlResult with URL and expiry time.

        Raises:
            FileNotFoundError: If the prompt doesn't exist in GCS.
        """
        object_name = _gcs_object_name(prompt_id)
        blob = self._bucket.blob(object_name)

        if not blob.exists():
            raise FileNotFoundError(f"Prompt '{prompt_id}' not found in GCS")

        expiration = datetime.timedelta(seconds=ttl_seconds)
        url = blob.generate_signed_url(
            expiration=expiration,
            method=method,
            version="v4",
        )
        expires_at = (
            datetime.datetime.now(datetime.timezone.utc) + expiration
        ).isoformat()

        logger.info("Signed URL generated for %s (ttl=%ds, method=%s)", prompt_id, ttl_seconds, method)
        return SignedUrlResult(
            prompt_id=prompt_id,
            url=url,
            expires_at=expires_at,
            method=method,
        )
