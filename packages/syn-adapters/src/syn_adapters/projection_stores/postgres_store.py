"""PostgreSQL projection store implementation.

This implementation persists projection data to PostgreSQL,
using per-projection tables for isolation and testability.
"""

from datetime import datetime
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
            # Use Syn137 Observability DB URL (ADR-030)
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
        from syn_adapters.projection_stores.postgres_helpers import ensure_projection_table

        pool = await self._get_pool()
        table_name = self._table_name(projection)
        await ensure_projection_table(pool, projection, table_name, self._initialized_tables)

    async def _ensure_state_table(self) -> None:
        """Ensure the projection_states table exists."""
        from syn_adapters.projection_stores.postgres_helpers import ensure_state_table

        pool = await self._get_pool()
        await ensure_state_table(pool, self._initialized_tables)

    def _table_name(self, projection: str) -> str:
        """Get the table name for a projection.

        Sanitizes the projection name to be a valid SQL identifier.
        """
        # Replace hyphens with underscores and ensure lowercase
        return projection.replace("-", "_").lower()

    def _serialize(self, data: dict[str, Any]) -> str:
        """Serialize data to JSON, handling datetime objects."""
        from syn_adapters.projection_stores.postgres_helpers import serialize

        return serialize(data)

    def _deserialize(self, data: str | dict[str, Any]) -> dict[str, Any]:
        """Deserialize JSON data."""
        from syn_adapters.projection_stores.postgres_helpers import deserialize

        return deserialize(data)

    @staticmethod
    def _json_serializer(obj: Any) -> Any:
        """JSON serializer for objects not serializable by default."""
        from syn_adapters.projection_stores.postgres_helpers import json_serializer

        return json_serializer(obj)

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
        from syn_adapters.projection_stores.postgres_helpers import fetch_get_all

        await self._ensure_table(projection)
        pool = await self._get_pool()
        table_name = self._table_name(projection)
        return await fetch_get_all(pool, table_name, self._deserialize)

    async def get_by_prefix(
        self, projection: str, prefix: str
    ) -> list[tuple[str, dict[str, Any]]]:
        """Get all records whose key starts with the given prefix."""
        await self._ensure_table(projection)
        pool = await self._get_pool()
        table_name = self._table_name(projection)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT id, data FROM {table_name} WHERE id LIKE $1 || '%%' LIMIT 10",
                prefix,
            )
            return [(row["id"], self._deserialize(row["data"])) for row in rows]

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
        from syn_adapters.projection_stores.postgres_helpers import execute_delete_all

        await self._ensure_table(projection)
        pool = await self._get_pool()
        table_name = self._table_name(projection)
        await execute_delete_all(pool, table_name, projection)

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

        from syn_adapters.projection_stores.postgres_query_builder import build_query

        query, params = build_query(table_name, filters, order_by, limit, offset)

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._deserialize(row["data"]) for row in rows]

    async def get_position(self, projection: str) -> int | None:
        """Get the last processed event position for a projection."""
        from syn_adapters.projection_stores.postgres_helpers import fetch_get_position

        await self._ensure_state_table()
        pool = await self._get_pool()
        return await fetch_get_position(pool, projection)

    async def set_position(self, projection: str, position: int) -> None:
        """Update the last processed event position for a projection."""
        from syn_adapters.projection_stores.postgres_helpers import execute_set_position

        await self._ensure_state_table()
        pool = await self._get_pool()
        await execute_set_position(pool, projection, position)

    async def get_last_updated(self, projection: str) -> datetime | None:
        """Get the last update timestamp for a projection."""
        from syn_adapters.projection_stores.postgres_helpers import fetch_get_last_updated

        await self._ensure_state_table()
        pool = await self._get_pool()
        return await fetch_get_last_updated(pool, projection)

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._initialized_tables.clear()
