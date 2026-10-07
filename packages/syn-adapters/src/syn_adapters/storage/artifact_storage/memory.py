"""In-memory artifact storage adapter - FOR TESTS ONLY.

See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from syn_adapters.in_memory import InMemoryAdapter, InMemoryAdapterError
from syn_adapters.storage.artifact_storage.minio_helpers import build_artifact_key
from syn_domain.contexts.artifacts.ports import ArtifactStorageError

# Re-export for backwards compatibility
TestOnlyAdapterError = InMemoryAdapterError


@dataclass(frozen=True)
class StorageResult:
    """Result of an artifact upload operation."""

    storage_uri: str
    content_hash: str
    size_bytes: int
    uploaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


class ArtifactNotFoundError(ArtifactStorageError):
    """Raised when an artifact is not found in storage."""

    def __init__(self, artifact_id: str) -> None:
        super().__init__(f"Artifact not found: {artifact_id}")


class InMemoryArtifactStorage(InMemoryAdapter):
    """In-memory artifact storage for unit tests.

    Inherits environment guard from InMemoryAdapter.
    Stores artifacts in a dict (lost on process exit).

    Objects are keyed exactly as MinioArtifactStorage keys them
    (``build_artifact_key``), so an upload made with a workflow or execution
    id is only found again through the ``storage_uri`` it returned, as in
    MinIO. Keyed by id alone, this fake served reads that 404'd in
    production (#990, #1652). ``tests/contract/test_artifact_storage_contract.py``
    holds both adapters to the same assertions.
    """

    _URI_SCHEME = "memory://"

    def __init__(self) -> None:
        """Initialize in-memory storage."""
        super().__init__()
        self._storage: dict[str, tuple[bytes, StorageResult]] = {}

    async def upload(
        self,
        artifact_id: str,
        content: bytes,
        *,
        workflow_id: str | None = None,
        phase_id: str | None = None,
        execution_id: str | None = None,
        content_type: str = "text/markdown",
        metadata: dict[str, Any] | None = None,
    ) -> StorageResult:
        """Upload artifact content to in-memory storage."""
        content_hash = hashlib.sha256(content).hexdigest()
        key = build_artifact_key(artifact_id, workflow_id, execution_id)
        storage_uri = f"{self._URI_SCHEME}{key}"

        result = StorageResult(
            storage_uri=storage_uri,
            content_hash=content_hash,
            size_bytes=len(content),
            metadata={
                "workflow_id": workflow_id,
                "phase_id": phase_id,
                "execution_id": execution_id,
                "content_type": content_type,
                **(metadata or {}),
            },
        )

        self._storage[key] = (content, result)
        return result

    async def download(self, artifact_id: str, *, storage_uri: str | None = None) -> bytes:
        """Download artifact content: from ``storage_uri`` when given, else the id-only key."""
        key = self._key_from_uri(storage_uri) or build_artifact_key(artifact_id)
        if key not in self._storage:
            raise ArtifactNotFoundError(artifact_id)
        return self._storage[key][0]

    async def delete(self, artifact_id: str) -> None:
        """Delete the artifact at its id-only key, as MinioArtifactStorage does."""
        self._storage.pop(build_artifact_key(artifact_id), None)

    async def exists(self, artifact_id: str) -> bool:
        """Check the artifact's id-only key, as MinioArtifactStorage does."""
        return build_artifact_key(artifact_id) in self._storage

    @classmethod
    def _key_from_uri(cls, storage_uri: str | None) -> str | None:
        if storage_uri and storage_uri.startswith(cls._URI_SCHEME):
            return storage_uri.removeprefix(cls._URI_SCHEME) or None
        return None

    def clear(self) -> None:
        """Clear all stored artifacts (for test cleanup)."""
        self._storage.clear()

    @property
    def count(self) -> int:
        """Get number of stored artifacts (for test assertions)."""
        return len(self._storage)
