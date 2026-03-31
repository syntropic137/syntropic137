"""Storage factory for creating storage adapters based on configuration.

Provides a factory function that creates the appropriate storage adapter
based on the SYN_STORAGE_* environment variables.

Usage:
    from syn_adapters.object_storage import get_storage

    # Returns LocalStorage or MinioStorage based on SYN_STORAGE_PROVIDER
    storage = await get_storage()
"""

from __future__ import annotations

from functools import lru_cache

from syn_adapters.object_storage.local import LocalStorage
from syn_adapters.object_storage.minio import MinioStorage
from syn_shared.settings import get_settings
from syn_shared.settings.storage import StorageProvider


@lru_cache
def _get_storage_instance() -> LocalStorage | MinioStorage:
    """Get cached storage instance based on configuration.

    Returns:
        Configured storage adapter.
    """
    settings = get_settings()
    storage_settings = settings.storage

    if storage_settings.provider == StorageProvider.MINIO:
        return MinioStorage(
            endpoint=storage_settings.minio_endpoint,
            access_key=storage_settings.minio_access_key,
            secret_key=storage_settings.minio_secret_key.get_secret_value(),
            bucket_name=storage_settings.bucket_name,
            secure=storage_settings.minio_secure,
        )

    # Default to local storage
    return LocalStorage(base_path=storage_settings.local_path)


async def get_storage() -> LocalStorage | MinioStorage:
    """Get storage adapter based on configuration.

    Creates and returns the appropriate storage adapter based on
    the SYN_STORAGE_* environment variables.

    Returns:
        StorageProtocol: Configured storage adapter.

    Example:
        storage = await get_storage()
        await storage.upload("key", b"content")
    """
    return _get_storage_instance()


def reset_storage() -> None:
    """Reset storage cache (for testing).

    Call this to force recreation of storage adapter.
    """
    _get_storage_instance.cache_clear()
