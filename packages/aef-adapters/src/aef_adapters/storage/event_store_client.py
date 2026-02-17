"""Event Store Client factory for AEF.

This module provides factory functions to create EventStoreClient instances
based on the application environment. See ADR-007 for architecture details.

Usage:
    # Get client based on environment
    client = get_event_store_client()

    # For tests (uses MemoryEventStoreClient)
    APP_ENVIRONMENT=test -> MemoryEventStoreClient

    # For development/production (uses GrpcEventStoreClient)
    APP_ENVIRONMENT=development -> GrpcEventStoreClient -> Event Store Server
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aef_shared.settings import get_settings

if TYPE_CHECKING:
    from event_sourcing import EventStoreClient

logger = logging.getLogger(__name__)

# Global client instance (managed lifecycle)
_client: EventStoreClient | None = None


def get_event_store_client() -> EventStoreClient:
    """Get or create an EventStoreClient based on environment.

    For TEST environment: Returns MemoryEventStoreClient (in-memory, fast)
    For other environments: Returns GrpcEventStoreClient (connects to Event Store Server)

    The client is lazily created and cached for reuse.

    Returns:
        EventStoreClient instance appropriate for the environment.

    Raises:
        RuntimeError: If Event Store Server is not reachable in non-test environments.
    """
    global _client

    if _client is not None:
        return _client

    settings = get_settings()

    _client = _create_memory_client() if settings.uses_in_memory_stores else _create_grpc_client()

    return _client


def _create_memory_client() -> EventStoreClient:
    """Create an in-memory client for testing."""
    from event_sourcing import EventStoreClientFactory

    logger.info("Creating in-memory EventStoreClient for tests")
    return EventStoreClientFactory.create_memory_client()


def _create_grpc_client() -> EventStoreClient:
    """Create a gRPC client for development/production."""
    from event_sourcing import EventStoreClientFactory

    settings = get_settings()

    logger.info(
        "Creating gRPC EventStoreClient",
        extra={
            "host": settings.event_store_host,
            "port": settings.event_store_port,
            "tenant_id": settings.event_store_tenant_id,
        },
    )

    return EventStoreClientFactory.create_grpc_client(
        host=settings.event_store_host,
        port=settings.event_store_port,
        tenant_id=settings.event_store_tenant_id,
    )


async def connect_event_store() -> None:
    """Connect to the event store (call on app startup).

    For gRPC client, establishes the connection to the Event Store Server.
    For memory client, this is a no-op.
    """
    client = get_event_store_client()
    await client.connect()
    logger.info("Connected to Event Store")


async def disconnect_event_store() -> None:
    """Disconnect from the event store (call on app shutdown).

    Cleans up connections and resources.
    """
    global _client

    if _client is not None:
        await _client.disconnect()
        _client = None
        logger.info("Disconnected from Event Store")


def reset_event_store_client() -> None:
    """Reset the client (for testing).

    Clears the cached client instance.
    """
    global _client
    _client = None
