"""Agent event store with batch inserts for high-throughput.

This replaces the ObservabilityWriter with a simpler, faster implementation
designed for 10K+ concurrent agents.

Key features:
- Batch inserts using PostgreSQL COPY for maximum throughput
- Simple schema (no complex observation types)
- TimescaleDB hypertable with compression
- Type-safe models via SQLModel (see models.py)

See ADR-029: Simplified Event System
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import asyncpg
from pydantic import ValidationError

from syn_adapters.events.models import AgentEvent
from syn_adapters.events.queries import (
    query_execution_events,
    query_recent_by_types as _query_recent_by_types,
    query_session_events,
)
from syn_adapters.events.schema import EventStoreSchema, SchemaValidationError  # noqa: F401
from syn_adapters.events.store_helpers import (
    RESERVED_OBSERVATION_KEYS,
    _build_copy_buffer,
    get_event_store as get_event_store,
)

logger = logging.getLogger(__name__)


class EventValidationError(Exception):
    """Raised when event data fails validation."""

    pass


class AgentEventStore:
    """Store agent events with batch inserts for scale.

    Performance target: 100K+ events/sec using COPY.

    Usage:
        store = AgentEventStore(connection_string)
        await store.initialize()

        # Insert events in batches for best performance
        await store.insert_batch([
            {"event_type": "tool_started", "session_id": "sess-1", ...},
            {"event_type": "tool_completed", "session_id": "sess-1", ...},
        ])

        # Query events
        events = await store.query("sess-1", event_type="tool_completed")
    """

    def __init__(self, connection_string: str, schema: EventStoreSchema | None = None) -> None:
        """Initialize the event store.

        Args:
            connection_string: PostgreSQL connection string for TimescaleDB
            schema: Optional EventStoreSchema instance for schema management.
                    If not provided, creates one using SYN_SKIP_AUTO_CREATE_TABLES env var.
        """
        self.conn_string = connection_string
        self.pool: asyncpg.Pool | None = None
        self._initialized = False
        self._schema = schema or EventStoreSchema(
            skip_auto_create=os.environ.get("SYN_SKIP_AUTO_CREATE_TABLES", "").lower() == "true"
        )

    async def initialize(self) -> None:
        """Initialize connection pool and create schema if needed."""
        if self._initialized:
            return

        self.pool = await asyncpg.create_pool(
            self.conn_string,
            min_size=5,
            max_size=20,
        )

        async with self.pool.acquire() as conn:
            await self._schema.ensure_schema(conn)  # type: ignore[arg-type]  # asyncpg PoolConnectionProxy is compatible with Connection

        self._initialized = True
        logger.info("AgentEventStore initialized")

    async def insert_batch(
        self,
        events: list[dict[str, Any]],
        execution_id: str | None = None,
        phase_id: str | None = None,
    ) -> int:
        """Insert a batch of events using COPY for maximum throughput.

        This is the recommended way to insert events - buffer them and
        insert in batches of 1000+ for best performance.

        Args:
            events: List of event dicts with at least 'event_type' and 'session_id'
            execution_id: Optional execution ID to add to all events
            phase_id: Optional phase ID to add to all events

        Returns:
            Number of events inserted
        """
        if not events:
            return 0

        if not self._initialized:
            await self.initialize()

        if self.pool is None:
            raise RuntimeError("AgentEventStore pool is not initialized")

        buffer = _build_copy_buffer(events, execution_id, phase_id)

        async with self.pool.acquire() as conn:
            result = await conn.copy_to_table(
                "agent_events",
                source=buffer,
                columns=["time", "event_type", "session_id", "execution_id", "phase_id", "data"],
                format="text",
            )

        if isinstance(result, str) and result.startswith("COPY"):
            count = int(result.split()[1])
        else:
            count = len(events)

        logger.debug("Inserted %d events", count)
        return count

    async def insert_one(
        self,
        event: dict[str, Any],
        execution_id: str | None = None,
        phase_id: str | None = None,
    ) -> None:
        """Insert a single event with type validation.

        For high-throughput, prefer insert_batch().

        Uses AgentEvent model for type validation before insert.
        This catches type mismatches at runtime with clear error messages.

        Args:
            event: Event dict with at least 'event_type' and 'session_id'
            execution_id: Optional execution ID
            phase_id: Optional phase ID

        Raises:
            EventValidationError: If event data fails validation
        """
        if not self._initialized:
            await self.initialize()

        if self.pool is None:
            raise RuntimeError("AgentEventStore pool is not initialized")

        # Add context IDs if not present
        if execution_id and "execution_id" not in event:
            event["execution_id"] = execution_id
        if phase_id and "phase_id" not in event:
            event["phase_id"] = phase_id

        # Validate through model (type-safe!)
        try:
            validated = AgentEvent.from_dict(event)
        except ValidationError as e:
            raise EventValidationError(f"Event validation failed: {e}") from e

        # Get insert tuple from validated model
        time, event_type, session_id, exec_id, ph_id, data_json = validated.to_insert_tuple()

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_events
                (time, event_type, session_id, execution_id, phase_id, data)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                time,
                event_type,
                session_id,
                exec_id,
                ph_id,
                data_json,
            )

    async def query(
        self,
        session_id: str,
        event_type: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query events for a session.

        Args:
            session_id: Session ID to query
            event_type: Optional event type filter
            limit: Maximum events to return
            offset: Offset for pagination

        Returns:
            List of event dicts with 'time', 'event_type', 'session_id', etc.
        """
        if not self._initialized:
            await self.initialize()

        if self.pool is None:
            raise RuntimeError("AgentEventStore pool is not initialized")

        return await query_session_events(
            self.pool, session_id, event_type=event_type, limit=limit, offset=offset
        )

    async def query_by_execution(
        self,
        execution_id: str,
        event_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query events for an execution.

        Args:
            execution_id: Execution ID to query
            event_type: Optional event type filter
            limit: Maximum events to return

        Returns:
            List of event dicts
        """
        if not self._initialized:
            await self.initialize()

        if self.pool is None:
            raise RuntimeError("AgentEventStore pool is not initialized")

        return await query_execution_events(
            self.pool, execution_id, event_type=event_type, limit=limit
        )

    async def query_recent_by_types(
        self,
        event_types: list[str],
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query most recent events of given types across all sessions.

        Used for the global activity feed (git commits, pushes, etc.).

        Args:
            event_types: Event type strings to include.
            limit: Maximum events to return.

        Returns:
            List of event dicts ordered by time DESC.
        """
        if not self._initialized:
            await self.initialize()

        if self.pool is None:
            raise RuntimeError("AgentEventStore pool is not initialized")

        return await _query_recent_by_types(self.pool, event_types, limit=limit)

    _RESERVED_OBSERVATION_KEYS = RESERVED_OBSERVATION_KEYS

    async def record_observation(
        self,
        session_id: str,
        observation_type: str,
        data: dict[str, Any],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        """Record an observation event (ObservabilityWriter interface for ADR-026).

        This method adapts the WorkflowExecutionEngine's observability API
        to the AgentEventStore's insert_one method.

        Args:
            session_id: Session ID
            observation_type: Type of observation (e.g., "token_usage", "tool_execution_started")
            data: Observation-specific payload. Must NOT contain reserved keys
                  (event_type, session_id, message, timestamp, etc.) — they are
                  silently dropped with a warning. Use field names specific to the
                  observation type (e.g., "commit_message" not "message").
            execution_id: Optional execution ID
            phase_id: Optional phase ID
            workspace_id: Optional workspace ID
        """
        if conflicting := (data.keys() & self._RESERVED_OBSERVATION_KEYS):
            logger.warning(
                "record_observation(%s): data contains reserved keys %s — "
                "they will be ignored to prevent event corruption. "
                "Rename the field(s) in the caller.",
                observation_type,
                sorted(conflicting),
            )
        safe_data = {k: v for k, v in data.items() if k not in self._RESERVED_OBSERVATION_KEYS}
        event = {
            "event_type": observation_type,
            "session_id": session_id,
            "timestamp": datetime.now(UTC),
            "workspace_id": workspace_id,
            **safe_data,
        }
        await self.insert_one(
            event=event,
            execution_id=execution_id,
            phase_id=phase_id,
        )

    async def close(self) -> None:
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None
            self._initialized = False
