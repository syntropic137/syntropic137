"""In-memory artifact storage adapter - FOR TESTS ONLY.

CRITICAL: This adapter throws TestOnlyAdapterError if AEF_ENVIRONMENT != 'test'.
This prevents accidental use in production/development where data would be lost.

Usage:
    # In tests only
    os.environ["AEF_ENVIRONMENT"] = "test"
    storage = InMemoryArtifactStorage()

See ADR-013: Integration Testing Strategy
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class TestOnlyAdapterError(Exception):
    """Raised when a test-only adapter is used outside test environment.

    This is a safety guard to prevent false positives in production.
    Memory implementations lose data on restart and should never be
    used outside of unit/integration tests.
    """

    def __init__(self, adapter_name: str) -> None:
        env = os.environ.get("AEF_ENVIRONMENT", "not set")
        super().__init__(
            f"{adapter_name} can only be used when AEF_ENVIRONMENT='test'. "
            f"Current value: '{env}'. "
            "This adapter is for testing only and would lose data in production."
        )


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


class InMemoryArtifactStorage:
    """In-memory artifact storage for unit tests.

    CRITICAL: Throws TestOnlyAdapterError if AEF_ENVIRONMENT != 'test'.

    This implementation:
    - Stores artifacts in a dict (lost on process exit)
    - Is fast for unit tests
    - Must NEVER be used in production

    Usage:
        # Ensure test environment
        os.environ["AEF_ENVIRONMENT"] = "test"

        storage = InMemoryArtifactStorage()
        result = await storage.upload("artifact-123", b"content")
        content = await storage.download("artifact-123")
    """

    def __init__(self) -> None:
        """Initialize in-memory storage.

        Raises:
            TestOnlyAdapterError: If AEF_ENVIRONMENT is not 'test'
        """
        env = os.environ.get("AEF_ENVIRONMENT", "")
        if env != "test":
            raise TestOnlyAdapterError("InMemoryArtifactStorage")

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
