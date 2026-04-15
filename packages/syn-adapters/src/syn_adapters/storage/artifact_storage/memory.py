"""In-memory artifact storage adapter - FOR TESTS ONLY.

See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from syn_adapters.in_memory import InMemoryAdapter, InMemoryAdapterError

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


class ArtifactNotFoundError(Exception):
    """Raised when an artifact is not found in storage."""

    def __init__(self, artifact_id: str) -> None:
        super().__init__(f"Artifact not found: {artifact_id}")


class InMemoryArtifactStorage(InMemoryAdapter):
    """In-memory artifact storage for unit tests.

    Inherits environment guard from InMemoryAdapter.
    Stores artifacts in a dict (lost on process exit).
    """

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
        storage_uri = f"memory://{artifact_id}"

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

        self._storage[artifact_id] = (content, result)
        return result

    async def download(self, artifact_id: str) -> bytes:
        """Download artifact content from in-memory storage."""
        if artifact_id not in self._storage:
            raise ArtifactNotFoundError(artifact_id)
        return self._storage[artifact_id][0]

    async def delete(self, artifact_id: str) -> None:
        """Delete artifact from in-memory storage."""
        self._storage.pop(artifact_id, None)

    async def exists(self, artifact_id: str) -> bool:
        """Check if artifact exists in in-memory storage."""
        return artifact_id in self._storage

    def clear(self) -> None:
        """Clear all stored artifacts (for test cleanup)."""
        self._storage.clear()

    @property
    def count(self) -> int:
        """Get number of stored artifacts (for test assertions)."""
        return len(self._storage)
