"""Storage adapters - persistence implementations.

This module provides storage adapters for both testing and production:

- **In-Memory** (testing only): Use for unit tests and fast feedback loops.
  These stores do NOT persist between runs.

- **PostgreSQL** (local dev & production): Use for local development via
  Docker and production environments. Start Docker with 'just dev'.

The get_* functions will automatically select the appropriate implementation
based on the APP_ENVIRONMENT and DATABASE_URL settings.
"""

from aef_adapters.storage.in_memory import (
    InMemoryEventPublisher,
    InMemoryEventStore,
    InMemoryWorkflowRepository,
    StoredEvent,
    get_event_publisher,
    get_event_store,
    get_workflow_repository,
    reset_storage,
)

# PostgreSQL implementations (lazy import to avoid requiring asyncpg in tests)
# Use get_postgres_* functions or import directly when DATABASE_URL is configured

__all__ = [
    "InMemoryEventPublisher",
    "InMemoryEventStore",
    "InMemoryWorkflowRepository",
    "StoredEvent",
    "close_connection_pool",
    "get_event_publisher",
    "get_event_store",
    "get_postgres_event_store",
    "get_postgres_workflow_repository",
    "get_workflow_repository",
    "reset_storage",
]


# Lazy imports for PostgreSQL to avoid requiring asyncpg in tests
def __getattr__(name: str) -> object:
    """Lazy import PostgreSQL implementations."""
    if name in (
        "get_postgres_event_store",
        "get_postgres_workflow_repository",
        "close_connection_pool",
    ):
        from aef_adapters.storage import postgres

        return getattr(postgres, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
