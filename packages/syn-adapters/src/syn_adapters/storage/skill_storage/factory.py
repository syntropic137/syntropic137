"""Skill storage factory - env-driven adapter selection (issue #772)."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from syn_shared.settings import get_settings
from syn_shared.settings.storage import StorageProvider

if TYPE_CHECKING:
    from syn_adapters.storage.skill_storage.memory import InMemorySkillStorage
    from syn_adapters.storage.skill_storage.minio import MinioSkillStorage

logger = logging.getLogger(__name__)


@lru_cache
def _get_skill_storage_instance() -> MinioSkillStorage:
    """Cached MinIO skill storage built from settings."""
    settings = get_settings()
    storage_settings = settings.storage

    if storage_settings.provider != StorageProvider.MINIO:
        msg = (
            "Skill storage requires SYN_STORAGE_PROVIDER=minio "
            f"(current: {storage_settings.provider}). Local provider not yet supported."
        )
        raise ValueError(msg)

    from syn_adapters.object_storage.minio import MinioStorage
    from syn_adapters.storage.skill_storage.minio import MinioSkillStorage

    minio_storage = MinioStorage(
        endpoint=storage_settings.minio_endpoint,
        access_key=storage_settings.minio_access_key,
        secret_key=storage_settings.minio_secret_key.get_secret_value(),
        bucket_name=storage_settings.skill_bucket_name,
        secure=storage_settings.minio_secure,
    )

    logger.info(
        "Created MinIO skill storage",
        extra={
            "endpoint": storage_settings.minio_endpoint,
            "bucket": storage_settings.skill_bucket_name,
        },
    )

    return MinioSkillStorage(minio_storage)


async def get_skill_storage() -> MinioSkillStorage:
    """Get the configured skill storage adapter."""
    return _get_skill_storage_instance()


def get_test_skill_storage() -> InMemorySkillStorage:
    """Get in-memory skill storage for tests.

    Raises ``InMemoryAdapterError`` if not in test/offline mode.
    """
    from syn_adapters.storage.skill_storage.memory import InMemorySkillStorage

    return InMemorySkillStorage()


def reset_skill_storage() -> None:
    """Reset the cached instance (for test isolation)."""
    _get_skill_storage_instance.cache_clear()
