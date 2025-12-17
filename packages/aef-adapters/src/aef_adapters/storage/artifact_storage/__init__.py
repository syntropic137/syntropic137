"""Artifact storage adapters for storing artifact content.

Implements ArtifactContentStoragePort from the domain layer.

Adapters:
- MinioArtifactStorage: Production/development (S3-compatible)
- InMemoryArtifactStorage: Unit tests ONLY (requires AEF_ENVIRONMENT='test')

Usage:
    from aef_adapters.storage.artifact_storage import get_artifact_storage

    # Get configured storage (based on AEF_STORAGE_PROVIDER)
    storage = await get_artifact_storage()
    result = await storage.upload("artifact-123", b"content")

For tests:
    import os
    os.environ["AEF_ENVIRONMENT"] = "test"

    from aef_adapters.storage.artifact_storage import get_test_artifact_storage
    storage = get_test_artifact_storage()

See ADR-012: Artifact Storage Architecture
"""

from aef_adapters.storage.artifact_storage.factory import (
    get_artifact_storage,
    get_test_artifact_storage,
    reset_artifact_storage,
)
from aef_adapters.storage.artifact_storage.memory import (
    ArtifactNotFoundError,
    InMemoryArtifactStorage,
    StorageResult,
    TestOnlyAdapterError,
)
from aef_adapters.storage.artifact_storage.minio import (
    MinioArtifactStorage,
    StorageError,
)

__all__ = [
    "ArtifactNotFoundError",
    "InMemoryArtifactStorage",
    "MinioArtifactStorage",
    "StorageError",
    "StorageResult",
    "TestOnlyAdapterError",
    "get_artifact_storage",
    "get_test_artifact_storage",
    "reset_artifact_storage",
]

