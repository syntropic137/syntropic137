"""PostgreSQL storage adapters for local development and production.

This module provides PostgreSQL-backed implementations of the repository
interfaces for use in local development (via Docker) and production.

WARNING: Requires DATABASE_URL to be configured.
For local dev: Start Docker with 'just dev' first.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aef_shared.logging import get_logger
from aef_shared.settings import get_settings

if TYPE_CHECKING:
    from uuid import UUID

    from aef_domain.contexts.workflows._shared.WorkflowAggregate import (
        WorkflowAggregate,
    )

logger = get_logger(__name__)


class PostgresEventStore:
    """PostgreSQL-backed event store.

    Stores events in the event_store.events table.
    This implementation is suitable for local development and production.
    """

    def __init__(self, connection_pool: Any) -> None:
        """Initialize with a connection pool.

        Args:
            connection_pool: asyncpg or psycopg connection pool.
        """
        self._pool = connection_pool
        self._sequence = 0

    async def append(
        self,
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        event_data: dict[str, Any],
        version: int,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Append an event to the store.

        Returns:
            The event ID.
        """
        event_id = str(uuid4())

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO event_store.events
                    (id, aggregate_type, aggregate_id, event_type, event_data, metadata, version)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                event_id,
                aggregate_type,
                aggregate_id,
                event_type,
                json.dumps(event_data),
                json.dumps(metadata or {}),
                version,
            )

        logger.debug(
            "Event appended",
            event_id=event_id,
            aggregate_id=aggregate_id,
            event_type=event_type,
        )
        return event_id

    async def get_events(self, aggregate_id: str) -> list[dict[str, Any]]:
        """Get all events for an aggregate, ordered by version."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, aggregate_type, aggregate_id, event_type,
                       event_data, metadata, version, created_at
                FROM event_store.events
                WHERE aggregate_id = $1
                ORDER BY version ASC
                """,
                aggregate_id,
            )

        return [
            {
                "id": str(row["id"]),
                "aggregate_type": row["aggregate_type"],
                "aggregate_id": str(row["aggregate_id"]),
                "event_type": row["event_type"],
                "event_data": json.loads(row["event_data"]),
                "metadata": json.loads(row["metadata"]),
                "version": row["version"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def get_all_events(
        self,
        after_sequence: int | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Get all events, optionally after a sequence number."""
        async with self._pool.acquire() as conn:
            if after_sequence is not None:
                rows = await conn.fetch(
                    """
                    SELECT id, aggregate_type, aggregate_id, event_type,
                           event_data, metadata, version, created_at
                    FROM event_store.events
                    WHERE id > $1
                    ORDER BY created_at ASC
                    LIMIT $2
                    """,
                    after_sequence,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, aggregate_type, aggregate_id, event_type,
                           event_data, metadata, version, created_at
                    FROM event_store.events
                    ORDER BY created_at ASC
                    LIMIT $1
                    """,
                    limit,
                )

        return [
            {
                "id": str(row["id"]),
                "aggregate_type": row["aggregate_type"],
                "aggregate_id": str(row["aggregate_id"]),
                "event_type": row["event_type"],
                "event_data": json.loads(row["event_data"]),
                "metadata": json.loads(row["metadata"]),
                "version": row["version"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


class PostgresWorkflowRepository:
    """PostgreSQL-backed repository for Workflow aggregates.

    Uses the event store to persist and load aggregates.
    """

    def __init__(self, event_store: PostgresEventStore) -> None:
        self._event_store = event_store

    async def save(self, aggregate: WorkflowAggregate) -> None:
        """Save the aggregate's uncommitted events to the store."""
        events = aggregate.get_uncommitted_events()

        for i, event_envelope in enumerate(events):
            event = event_envelope.event
            event_data = event.model_dump() if hasattr(event, "model_dump") else {}

            await self._event_store.append(
                aggregate_id=str(aggregate.id) if aggregate.id else "",
                aggregate_type=aggregate.get_aggregate_type(),
                event_type=getattr(event, "event_type", type(event).__name__),
                event_data=event_data,
                version=aggregate.version + i + 1,
            )

        logger.info(
            "Aggregate saved",
            aggregate_id=str(aggregate.id),
            events_saved=len(events),
        )

    async def get_by_id(self, workflow_id: str | UUID) -> WorkflowAggregate | None:
        """Retrieve a workflow by ID, replaying events."""
        from event_sourcing import EventEnvelope, EventMetadata

        from aef_domain.contexts.workflows._shared.WorkflowAggregate import (
            WorkflowAggregate,
        )
        from aef_domain.contexts.workflows.create_workflow.WorkflowCreatedEvent import (
            WorkflowCreatedEvent,
        )

        str_id = str(workflow_id)
        stored_events = await self._event_store.get_events(str_id)

        if not stored_events:
            return None

        aggregate = WorkflowAggregate()

        envelopes: list[EventEnvelope[WorkflowCreatedEvent]] = []
        for stored_event in stored_events:
            if stored_event["event_type"] == "WorkflowCreated":
                event = WorkflowCreatedEvent(**stored_event["event_data"])
                metadata = EventMetadata(
                    event_id=stored_event["id"],
                    aggregate_id=stored_event["aggregate_id"],
                    aggregate_type=stored_event["aggregate_type"],
                    aggregate_nonce=stored_event["version"],
                )
                envelope = EventEnvelope(event=event, metadata=metadata)
                envelopes.append(envelope)

        aggregate.rehydrate(envelopes)

        logger.debug(
            "Aggregate rehydrated",
            aggregate_id=str_id,
            events_replayed=len(envelopes),
        )
        return aggregate


# Connection pool management
_connection_pool: Any | None = None


async def get_connection_pool() -> Any:
    """Get or create a connection pool.

    Lazily creates a connection pool on first call.
    Requires DATABASE_URL to be configured.
    """
    global _connection_pool

    if _connection_pool is not None:
        return _connection_pool

    settings = get_settings()
    if settings.database_url is None:
        msg = (
            "DATABASE_URL not configured. "
            "For local development, run 'just dev' to start Docker services."
        )
        raise RuntimeError(msg)

    try:
        import asyncpg

        _connection_pool = await asyncpg.create_pool(
            str(settings.database_url),
            min_size=settings.database_pool_size,
            max_size=settings.database_pool_size + settings.database_pool_overflow,
        )
        logger.info(
            "PostgreSQL connection pool created",
            pool_size=settings.database_pool_size,
        )
        return _connection_pool
    except ImportError as e:
        msg = "asyncpg not installed. Install with: uv add asyncpg"
        raise RuntimeError(msg) from e


async def close_connection_pool() -> None:
    """Close the connection pool."""
    global _connection_pool
    if _connection_pool is not None:
        await _connection_pool.close()
        _connection_pool = None
        logger.info("PostgreSQL connection pool closed")


# Factory functions for dependency injection
async def get_postgres_event_store() -> PostgresEventStore:
    """Get a PostgreSQL event store instance."""
    pool = await get_connection_pool()
    return PostgresEventStore(pool)


async def get_postgres_workflow_repository() -> PostgresWorkflowRepository:
    """Get a PostgreSQL workflow repository instance."""
    event_store = await get_postgres_event_store()
    return PostgresWorkflowRepository(event_store)
