"""Artifact storage factory - creates the appropriate adapter based on configuration.

Selects storage adapter based on SYN_STORAGE_PROVIDER environment variable:
- 'minio': Uses MinioArtifactStorage (default for development)
- 'local': Uses LocalArtifactStorage (filesystem)
- For tests: InMemoryArtifactStorage (requires SYN_ENVIRONMENT='test')

See ADR-012: Artifact Storage Architecture
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from syn_shared.settings import get_settings
from syn_shared.settings.storage import StorageProvider

if TYPE_CHECKING:
    from syn_adapters.storage.artifact_storage.memory import InMemoryArtifactStorage
    from syn_adapters.storage.artifact_storage.minio import MinioArtifactStorage

logger = logging.getLogger(__name__)


@lru_cache
def _get_artifact_storage_instance() -> MinioArtifactStorage:
    """Get cached artifact storage instance based on configuration.

    Returns:
        Configured artifact storage adapter.

    Raises:
        ValueError: If required configuration is missing.
    """
    settings = get_settings()
    storage_settings = settings.storage

    if storage_settings.provider == StorageProvider.MINIO:
        from syn_adapters.object_storage.minio import MinioStorage
        from syn_adapters.storage.artifact_storage.minio import MinioArtifactStorage

        # Create underlying MinIO client
        minio_storage = MinioStorage(
            endpoint=storage_settings.minio_endpoint,
            access_key=storage_settings.minio_access_key,
            secret_key=storage_settings.minio_secret_key.get_secret_value(),
            bucket_name=storage_settings.bucket_name,
            secure=storage_settings.minio_secure,
        )

        logger.info(
            "Created MinIO artifact storage",
            extra={
                "endpoint": storage_settings.minio_endpoint,
                "bucket": storage_settings.bucket_name,
            },
        )

        return MinioArtifactStorage(minio_storage)

    if storage_settings.provider == StorageProvider.LOCAL:
        # For local storage, we still use MinIO adapter with local path
        # This maintains the same interface
        msg = (
            "Local artifact storage not yet implemented. "
            "Use SYN_STORAGE_PROVIDER=minio with MinIO for development."
        )
        raise ValueError(msg)

    msg = f"Unsupported storage provider for artifacts: {storage_settings.provider}"
    raise ValueError(msg)


async def get_artifact_storage() -> MinioArtifactStorage:
    """Get artifact storage adapter based on configuration.

    Returns:
        Configured artifact storage adapter.

    Usage:
        storage = await get_artifact_storage()
        result = await storage.upload("artifact-123", b"content")
    """
    return _get_artifact_storage_instance()


def get_test_artifact_storage() -> InMemoryArtifactStorage:
    """Get in-memory artifact storage for tests.

    CRITICAL: Only works when SYN_ENVIRONMENT='test'.
    Throws TestOnlyAdapterError otherwise.

    Usage:
        # In test setup
        os.environ["SYN_ENVIRONMENT"] = "test"
        storage = get_test_artifact_storage()
    """
    from syn_adapters.storage.artifact_storage.memory import InMemoryArtifactStorage

    return InMemoryArtifactStorage()


def reset_artifact_storage() -> None:
    """Reset the cached artifact storage instance (for testing)."""
    _get_artifact_storage_instance.cache_clear()
