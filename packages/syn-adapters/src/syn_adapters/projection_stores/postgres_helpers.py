"""PostgreSQL projection store helpers.

Extracted from postgres_store.py to reduce module complexity.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import asyncpg


def serialize(data: dict[str, Any]) -> str:
    """Serialize data to JSON, handling datetime objects."""
    return json.dumps(data, default=json_serializer)


def deserialize(data: str | dict[str, Any]) -> dict[str, Any]:
    """Deserialize JSON data."""
    if isinstance(data, dict):
        return data
    result: dict[str, Any] = json.loads(data)
    return result


def json_serializer(obj: object) -> str:
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


async def ensure_projection_table(
    pool: asyncpg.Pool,
    projection: str,
    table_name: str,
    initialized_tables: set[str],
) -> None:
    """Ensure the projection table exists, creating it if necessary."""
    if projection in initialized_tables:
        return

    async with pool.acquire() as conn:
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id VARCHAR(255) PRIMARY KEY,
                data JSONB NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        # Create index on updated_at for efficient queries
        await conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{table_name}_updated_at
            ON {table_name}(updated_at DESC)
        """)

    initialized_tables.add(projection)


async def ensure_state_table(
    pool: asyncpg.Pool,
    initialized_tables: set[str],
) -> None:
    """Ensure the projection_states table exists."""
    if "_projection_states" in initialized_tables:
        return

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS projection_states (
                projection_name VARCHAR(255) PRIMARY KEY,
                last_event_position BIGINT DEFAULT 0,
                last_event_id VARCHAR(255),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

    initialized_tables.add("_projection_states")


async def fetch_get_all(
    pool: asyncpg.Pool,
    table_name: str,
    deserialize_fn: Callable[[str | dict[str, Any]], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fetch all records from a projection table ordered by updated_at."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"SELECT data FROM {table_name} ORDER BY updated_at DESC")
        return [deserialize_fn(row["data"]) for row in rows]


async def execute_delete_all(
    pool: asyncpg.Pool,
    table_name: str,
    projection: str,
) -> None:
    """Delete all records from a projection table and log the count."""
    async with pool.acquire() as conn:
        result = await conn.execute(f"DELETE FROM {table_name}")
        count = int(result.split()[-1]) if result else 0

    from syn_shared.logging import get_logger

    logger = get_logger(__name__)
    logger.info(
        "Deleted all projection records",
        extra={"projection": projection, "count": count},
    )


async def fetch_get_position(
    pool: asyncpg.Pool,
    projection: str,
) -> int | None:
    """Get the last processed event position for a projection."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT last_event_position FROM projection_states
            WHERE projection_name = $1
        """,
            projection,
        )
        if row:
            position_value: int = row["last_event_position"]
            return position_value
        return None


async def execute_set_position(
    pool: asyncpg.Pool,
    projection: str,
    position: int,
) -> None:
    """Update the last processed event position for a projection."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO projection_states (projection_name, last_event_position, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (projection_name) DO UPDATE SET
                last_event_position = EXCLUDED.last_event_position,
                updated_at = NOW()
        """,
            projection,
            position,
        )


async def fetch_get_last_updated(
    pool: asyncpg.Pool,
    projection: str,
) -> datetime | None:
    """Get the last update timestamp for a projection."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT updated_at FROM projection_states
            WHERE projection_name = $1
        """,
            projection,
        )
        if row:
            updated: datetime = row["updated_at"].replace(tzinfo=UTC)
            return updated
        return None
