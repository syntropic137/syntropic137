"""Standalone query functions for the agent event store.

Extracted from AgentEventStore to reduce module complexity.
Each function takes an asyncpg pool and query parameters,
returning structured dicts.

See ADR-029: Simplified Event System
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg


async def query_session_events(
    pool: asyncpg.Pool,
    session_id: str,
    event_type: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query events for a session.

    Args:
        pool: asyncpg connection pool
        session_id: Session ID to query
        event_type: Optional event type filter
        limit: Maximum events to return
        offset: Offset for pagination

    Returns:
        List of event dicts with 'time', 'event_type', 'session_id', etc.
    """
    async with pool.acquire() as conn:
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


async def query_execution_events(
    pool: asyncpg.Pool,
    execution_id: str,
    event_type: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Query events for an execution.

    Args:
        pool: asyncpg connection pool
        execution_id: Execution ID to query
        event_type: Optional event type filter
        limit: Maximum events to return

    Returns:
        List of event dicts
    """
    async with pool.acquire() as conn:
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
    pool: asyncpg.Pool,
    event_types: list[str],
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Query most recent events of given types across all sessions.

    Used for the global activity feed (git commits, pushes, etc.).

    Args:
        pool: asyncpg connection pool
        event_types: Event type strings to include.
        limit: Maximum events to return.

    Returns:
        List of event dicts ordered by time DESC.
    """
    async with pool.acquire() as conn:
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
