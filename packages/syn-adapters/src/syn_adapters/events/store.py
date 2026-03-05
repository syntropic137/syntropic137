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

import io
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import asyncpg
from pydantic import ValidationError

from syn_adapters.events.models import AgentEvent
from syn_adapters.events.schema import EventStoreSchema, SchemaValidationError  # noqa: F401

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
            await self._schema.ensure_schema(conn)

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

        # Build COPY data as bytes
        buffer = io.BytesIO()

        for event in events:
            # Add context IDs if provided
            if execution_id and "execution_id" not in event:
                event = {**event, "execution_id": execution_id}
            if phase_id and "phase_id" not in event:
                event = {**event, "phase_id": phase_id}

            # Process through AgentEvent model for proper type mapping and data extraction
            # This handles Claude CLI's nested event structure (tool_use, tool_result)
            try:
                validated = AgentEvent.from_dict(event)
            except Exception as e:
                logger.warning("Skipping invalid event: %s", e)
                continue

            # Get insert tuple from validated model
            time, event_type, session_id, evt_exec_id, evt_phase_id, data_json = (
                validated.to_insert_tuple()
            )

            # Write tab-separated row
            # Format: time, event_type, session_id, execution_id, phase_id, data
            row = [
                time.isoformat() if isinstance(time, datetime) else time,
                event_type,
                session_id or "unknown",
                evt_exec_id or "\\N",  # NULL representation
                evt_phase_id or "\\N",
                data_json,
            ]
            line = "\t".join(str(v) for v in row) + "\n"
            buffer.write(line.encode("utf-8"))

        buffer.seek(0)

        async with self.pool.acquire() as conn:
            result = await conn.copy_to_table(
                "agent_events",
                source=buffer,
                columns=["time", "event_type", "session_id", "execution_id", "phase_id", "data"],
                format="text",
            )

        # Parse result to get count
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

        async with self.pool.acquire() as conn:
            if event_type:
                rows = await conn.fetch(
                    """
                    SELECT time, event_type, session_id, execution_id, phase_id, data
                    FROM agent_events
                    WHERE session_id = $1 AND event_type = $2
                    ORDER BY time DESC
                    LIMIT $3 OFFSET $4
                    """,
                    session_id,
                    event_type,
                    limit,
                    offset,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT time, event_type, session_id, execution_id, phase_id, data
                    FROM agent_events
                    WHERE session_id = $1
                    ORDER BY time DESC
                    LIMIT $2 OFFSET $3
                    """,
                    session_id,
                    limit,
                    offset,
                )

        return [
            {
                "time": row["time"],
                "event_type": row["event_type"],
                "session_id": row["session_id"],
                "execution_id": row["execution_id"],
                "phase_id": row["phase_id"],
                "data": json.loads(row["data"]) if isinstance(row["data"], str) else row["data"],
            }
            for row in rows
        ]

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

        async with self.pool.acquire() as conn:
            if event_type:
                rows = await conn.fetch(
                    """
                    SELECT time, event_type, session_id, execution_id, phase_id, data
                    FROM agent_events
                    WHERE execution_id = $1 AND event_type = $2
                    ORDER BY time DESC
                    LIMIT $3
                    """,
                    execution_id,
                    event_type,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT time, event_type, session_id, execution_id, phase_id, data
                    FROM agent_events
                    WHERE execution_id = $1
                    ORDER BY time DESC
                    LIMIT $2
                    """,
                    execution_id,
                    limit,
                )

        return [
            {
                "timestamp": row["time"].isoformat(),
                "event_type": row["event_type"],
                "session_id": row["session_id"],
                "execution_id": row["execution_id"],
                "phase_id": row["phase_id"],
                **json.loads(row["data"]),
            }
            for row in rows
        ]

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

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT time, event_type, session_id, execution_id, phase_id, data
                FROM agent_events
                WHERE event_type = ANY($1)
                ORDER BY time DESC
                LIMIT $2
                """,
                event_types,
                limit,
            )

        return [
            {
                "time": row["time"].isoformat(),
                "event_type": row["event_type"],
                "session_id": row["session_id"],
                "execution_id": row["execution_id"],
                "phase_id": row["phase_id"],
                "data": json.loads(row["data"]) if isinstance(row["data"], str) else row["data"],
            }
            for row in rows
        ]

    # Keys in the top-level event dict that must NOT be overridden by user data.
    # AgentEvent.from_dict() uses "message" to detect Claude conversation messages,
    # and the other keys are event metadata. Collisions silently corrupt stored events.
    _RESERVED_OBSERVATION_KEYS: frozenset[str] = frozenset(
        {
            "event_type",
            "type",
            "session_id",
            "execution_id",
            "phase_id",
            "workspace_id",
            "timestamp",
            "time",
            "id",
            # "message" is reserved: from_dict() calls message.get("content", []) to detect
            # Claude tool_use/tool_result content blocks. A string "message" value crashes it.
            "message",
        }
    )

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


# Singleton instance (lazy-loaded)
_event_store: AgentEventStore | None = None


def get_event_store(connection_string: str | None = None) -> AgentEventStore:
    """Get or create the AgentEventStore singleton.

    Uses SYN_OBSERVABILITY_DB_URL from settings (ADR-030 unified database).

    Args:
        connection_string: Optional connection string (uses settings if not provided)

    Returns:
        AgentEventStore instance

    Raises:
        ValueError: If SYN_OBSERVABILITY_DB_URL is not configured
    """
    global _event_store

    if _event_store is None:
        if connection_string is None:
            from syn_shared.settings.config import get_settings

            settings = get_settings()

            if not settings.syn_observability_db_url:
                raise ValueError(
                    "SYN_OBSERVABILITY_DB_URL must be configured. "
                    "Set it in your .env file: "
                    "SYN_OBSERVABILITY_DB_URL=postgresql://user:pass@host:port/database"
                )

            connection_string = str(settings.syn_observability_db_url)

        _event_store = AgentEventStore(connection_string)

    return _event_store
