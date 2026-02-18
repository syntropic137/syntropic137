"""PostgreSQL projection store implementation.

This implementation persists projection data to PostgreSQL,
using per-projection tables for isolation and testability.
"""

import json
from datetime import UTC, datetime
from typing import Any

import asyncpg

from syn_shared.settings import get_settings


class PostgresProjectionStore:
    """PostgreSQL implementation of ProjectionStoreProtocol.

    Uses per-projection tables with a consistent schema:
    - id: Primary key (the record key)
    - data: JSONB column containing the projection data
    - created_at: Timestamp when record was created
    - updated_at: Timestamp when record was last updated

    Also maintains a projection_states table for position tracking.
    """

    def __init__(self, pool: asyncpg.Pool | None = None):
        """Initialize the store.

        Args:
            pool: Optional connection pool. If not provided,
                  a new pool will be created on first use.
        """
        self._pool = pool
        self._initialized_tables: set[str] = set()

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create the connection pool."""
        if self._pool is None:
            settings = get_settings()
            # Use AEF Observability DB URL (ADR-030)
            if not settings.syn_observability_db_url:
                raise ValueError(
                    "SYN_OBSERVABILITY_DB_URL must be configured. Set it in your .env file."
                )
            database_url = str(settings.syn_observability_db_url)
            self._pool = await asyncpg.create_pool(
                database_url,
                min_size=2,
                max_size=10,
            )
        return self._pool

    async def _ensure_table(self, projection: str) -> None:
        """Ensure the projection table exists."""
        if projection in self._initialized_tables:
            return

        pool = await self._get_pool()
        table_name = self._table_name(projection)

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

        self._initialized_tables.add(projection)

    async def _ensure_state_table(self) -> None:
        """Ensure the projection_states table exists."""
        if "_projection_states" in self._initialized_tables:
            return

        pool = await self._get_pool()

        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS projection_states (
                    projection_name VARCHAR(255) PRIMARY KEY,
                    last_event_position BIGINT DEFAULT 0,
                    last_event_id VARCHAR(255),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)

        self._initialized_tables.add("_projection_states")

    def _table_name(self, projection: str) -> str:
        """Get the table name for a projection.

        Sanitizes the projection name to be a valid SQL identifier.
        """
        # Replace hyphens with underscores and ensure lowercase
        return projection.replace("-", "_").lower()

    def _serialize(self, data: dict[str, Any]) -> str:
        """Serialize data to JSON, handling datetime objects."""
        return json.dumps(data, default=self._json_serializer)

    def _deserialize(self, data: str | dict[str, Any]) -> dict[str, Any]:
        """Deserialize JSON data."""
        if isinstance(data, dict):
            return data
        result: dict[str, Any] = json.loads(data)
        return result

    @staticmethod
    def _json_serializer(obj: Any) -> Any:
        """JSON serializer for objects not serializable by default."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        """Save or update a projection record."""
        await self._ensure_table(projection)
        pool = await self._get_pool()
        table_name = self._table_name(projection)

        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {table_name} (id, data, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    data = EXCLUDED.data,
                    updated_at = NOW()
            """,
                key,
                self._serialize(data),
            )

    async def get(self, projection: str, key: str) -> dict[str, Any] | None:
        """Get a single projection record by key."""
        await self._ensure_table(projection)
        pool = await self._get_pool()
        table_name = self._table_name(projection)

        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT data FROM {table_name} WHERE id = $1", key)
            if row:
                return self._deserialize(row["data"])
            return None

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        """Get all records for a projection."""
        await self._ensure_table(projection)
        pool = await self._get_pool()
        table_name = self._table_name(projection)

        async with pool.acquire() as conn:
            rows = await conn.fetch(f"SELECT data FROM {table_name} ORDER BY updated_at DESC")
            return [self._deserialize(row["data"]) for row in rows]

    async def delete(self, projection: str, key: str) -> None:
        """Delete a projection record."""
        await self._ensure_table(projection)
        pool = await self._get_pool()
        table_name = self._table_name(projection)

        async with pool.acquire() as conn:
            await conn.execute(f"DELETE FROM {table_name} WHERE id = $1", key)

    async def delete_all(self, projection: str) -> None:
        """Delete all records for a projection.

        Used during projection rebuild when version changes.
        """
        await self._ensure_table(projection)
        pool = await self._get_pool()
        table_name = self._table_name(projection)

        async with pool.acquire() as conn:
            result = await conn.execute(f"DELETE FROM {table_name}")
            # Extract count from result string like "DELETE 6"
            count = int(result.split()[-1]) if result else 0

        from syn_shared.logging import get_logger

        logger = get_logger(__name__)
        logger.info(
            "Deleted all projection records",
            extra={"projection": projection, "count": count},
        )

    async def query(
        self,
        projection: str,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query projection records with optional filtering."""
        await self._ensure_table(projection)
        pool = await self._get_pool()
        table_name = self._table_name(projection)

        # Build query
        query = f"SELECT data FROM {table_name}"
        params: list[Any] = []
        param_idx = 1

        # Apply filters (JSONB containment)
        if filters:
            conditions = []
            for key, value in filters.items():
                conditions.append(f"data->>'{key}' = ${param_idx}")
                params.append(str(value))
                param_idx += 1
            query += " WHERE " + " AND ".join(conditions)

        # Apply sorting
        if order_by:
            if order_by.startswith("-"):
                field = order_by[1:]
                direction = "DESC"
            else:
                field = order_by
                direction = "ASC"
            query += f" ORDER BY data->>'{field}' {direction}"
        else:
            query += " ORDER BY updated_at DESC"

        # Apply pagination
        if limit:
            query += f" LIMIT {limit}"
        if offset:
            query += f" OFFSET {offset}"

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._deserialize(row["data"]) for row in rows]

    async def get_position(self, projection: str) -> int | None:
        """Get the last processed event position for a projection."""
        await self._ensure_state_table()
        pool = await self._get_pool()

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

    async def set_position(self, projection: str, position: int) -> None:
        """Update the last processed event position for a projection."""
        await self._ensure_state_table()
        pool = await self._get_pool()

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

    async def get_last_updated(self, projection: str) -> datetime | None:
        """Get the last update timestamp for a projection."""
        await self._ensure_state_table()
        pool = await self._get_pool()

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

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._initialized_tables.clear()
