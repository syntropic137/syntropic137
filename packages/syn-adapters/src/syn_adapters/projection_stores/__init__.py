"""Projection store adapters for CQRS read models.

This module provides storage implementations for projection read models,
following the Vertical Slice Architecture pattern.

Usage:
    from syn_adapters.projection_stores import get_projection_store

    store = get_projection_store()
    await store.save("workflow_summaries", workflow_id, data)
    result = await store.get("workflow_summaries", workflow_id)
"""

from functools import lru_cache

from syn_shared.settings import get_settings

from .memory_store import InMemoryProjectionStore
from .postgres_store import PostgresProjectionStore
from .protocol import ProjectionStoreProtocol

__all__ = [
    "InMemoryProjectionStore",
    "PostgresProjectionStore",
    "ProjectionStoreProtocol",
    "get_projection_store",
]

# Module-level instance for singleton pattern
_store_instance: ProjectionStoreProtocol | None = None


@lru_cache
def get_projection_store() -> ProjectionStoreProtocol:
    """Get the projection store instance.

    Returns:
        InMemoryProjectionStore for test environments,
        PostgresProjectionStore for development/production.

    Note:
        This function is cached, so it returns the same instance
        on subsequent calls.
    """
    global _store_instance

    if _store_instance is not None:
        return _store_instance

    settings = get_settings()
    _store_instance = InMemoryProjectionStore() if settings.is_test else PostgresProjectionStore()
    return _store_instance


def reset_projection_store() -> None:
    """Reset the projection store instance.

    Useful for testing to ensure a fresh instance.
    """
    global _store_instance
    get_projection_store.cache_clear()
    _store_instance = None
