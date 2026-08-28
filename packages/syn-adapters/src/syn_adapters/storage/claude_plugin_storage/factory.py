"""Claude plugin storage factory - env-driven adapter selection (issue #726)."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from syn_shared.settings import get_settings
from syn_shared.settings.storage import StorageProvider

if TYPE_CHECKING:
    from syn_adapters.storage.claude_plugin_storage.memory import InMemoryClaudePluginStorage
    from syn_adapters.storage.claude_plugin_storage.minio import MinioClaudePluginStorage

logger = logging.getLogger(__name__)


@lru_cache
def _get_claude_plugin_storage_instance() -> MinioClaudePluginStorage:
    """Cached MinIO claude plugin storage built from settings."""
    settings = get_settings()
    storage_settings = settings.storage

    if storage_settings.provider != StorageProvider.MINIO:
        msg = (
            "Claude plugin storage requires SYN_STORAGE_PROVIDER=minio "
            f"(current: {storage_settings.provider}). Local provider not yet supported."
        )
        raise ValueError(msg)

    from syn_adapters.object_storage.minio import MinioStorage
    from syn_adapters.storage.claude_plugin_storage.minio import MinioClaudePluginStorage

    minio_storage = MinioStorage(
        endpoint=storage_settings.minio_endpoint,
        access_key=storage_settings.minio_access_key,
        secret_key=storage_settings.minio_secret_key.get_secret_value(),
        bucket_name=storage_settings.claude_plugin_bucket_name,
        secure=storage_settings.minio_secure,
    )

    logger.info(
        "Created MinIO claude plugin storage",
        extra={
            "endpoint": storage_settings.minio_endpoint,
            "bucket": storage_settings.claude_plugin_bucket_name,
        },
    )

    return MinioClaudePluginStorage(minio_storage)


async def get_claude_plugin_storage() -> MinioClaudePluginStorage:
    """Get the configured claude plugin storage adapter."""
    return _get_claude_plugin_storage_instance()


def get_test_claude_plugin_storage() -> InMemoryClaudePluginStorage:
    """Get in-memory claude plugin storage for tests.

    Raises ``InMemoryAdapterError`` if not in test/offline mode.
    """
    from syn_adapters.storage.claude_plugin_storage.memory import InMemoryClaudePluginStorage

    return InMemoryClaudePluginStorage()


def reset_claude_plugin_storage() -> None:
    """Reset the cached instance (for test isolation)."""
    _get_claude_plugin_storage_instance.cache_clear()
