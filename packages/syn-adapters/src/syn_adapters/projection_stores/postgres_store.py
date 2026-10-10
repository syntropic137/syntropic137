"""PostgreSQL projection store implementation.

This implementation persists projection data to PostgreSQL,
using per-projection tables for isolation and testability.
"""

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import asyncpg
from pydantic import BaseModel

from syn_adapters import postgres_pool
from syn_adapters.postgres_text import pg_safe
from syn_adapters.projection_stores.record_match import holds
from syn_domain.pagination import Page, ProjectionRecord
from syn_domain.projection_count import GroupKey
from syn_domain.projection_page import PageQuery
from syn_domain.projection_scan import Decide, JsonValue, SqlPage, SqlPageRequest
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
        # Tables whose lean column (lean_documents) is ready for list scans.
        self._lean_tables: set[str] = set()
        # Background list-index builds (postgres_page), held so they are not
        # collected mid-flight and can be cancelled on close.
        self._index_builds: set[asyncio.Task[None]] = set()

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
            self._pool = await postgres_pool.create_pool(
                database_url,
                name="projections",
                min_size=2,
                max_size=10,
            )
        return self._pool

    async def _ensure_table(self, projection: str) -> None:
        """Ensure the projection table exists."""
        from syn_adapters.projection_stores.postgres_helpers import ensure_projection_table

        pool = await self._get_pool()
        table_name = self._table_name(projection)
        if projection in self._initialized_tables:
            return
        await ensure_projection_table(pool, projection, table_name, self._initialized_tables)
        from syn_adapters.projection_stores.lean_documents import ensure_lean_column

        if await ensure_lean_column(pool, projection, table_name):
            self._lean_tables.add(projection)
        from syn_adapters.projection_stores.postgres_page import (
            LIST_FILTER_INDEXES,
            LIST_WINDOW_INDEXES,
            ensure_list_indexes,
        )
        from syn_adapters.projection_stores.postgres_page_keys import ensure_instant_function

        # Before the first page is read: a windowed page calls it.
        await ensure_instant_function(pool)
        if projection in LIST_FILTER_INDEXES or projection in LIST_WINDOW_INDEXES:
            # In the background: a CONCURRENTLY build waits out every open
            # transaction on the table, and no request should wait with it.
            build = asyncio.create_task(ensure_list_indexes(pool, projection, table_name))
            self._index_builds.add(build)
            build.add_done_callback(self._index_builds.discard)

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
    def _json_serializer(obj: object) -> str:
        """JSON serializer for objects not serializable by default."""
        from syn_adapters.projection_stores.postgres_helpers import json_serializer

        return json_serializer(obj)

    # A projection key is a session or execution id, and a harness supplies its
    # own, so it is untrusted text in a TEXT primary key. Every method below
    # normalises it through ``pg_safe`` before using it as a key OR as a lookup,
    # together: sanitising only the write stores the row under a name the read
    # cannot ask for, and a delete that matches nothing reports success (#1241).

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        """Save or update a projection record."""
        await self._ensure_table(projection)
        key = pg_safe(key)
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

    async def save_if(
        self, projection: str, key: str, record: BaseModel, *, expected: BaseModel | None
    ) -> bool:
        """Save only while the store still holds ``expected``. True if saved.

        One transaction. An existing row is locked (`FOR UPDATE`) before it is
        compared, so no other writer can change it between the comparison and
        the update. For no row, the insert itself is the check: `ON CONFLICT DO
        NOTHING` inserts nothing if another writer inserted first.
        """
        data = self._serialize(record.model_dump(mode="json"))
        await self._ensure_table(projection)
        key = pg_safe(key)
        pool = await self._get_pool()
        table_name = self._table_name(projection)

        async with pool.acquire() as conn, conn.transaction():
            if expected is None:
                status = await conn.execute(
                    f"""
                    INSERT INTO {table_name} (id, data, updated_at)
                    VALUES ($1, $2::jsonb, NOW())
                    ON CONFLICT (id) DO NOTHING
                """,
                    key,
                    data,
                )
                return status == "INSERT 0 1"
            row = await conn.fetchrow(
                f"SELECT data FROM {table_name} WHERE id = $1 FOR UPDATE", key
            )
            if row is None or not holds(self._deserialize(row["data"]), expected):
                return False
            await conn.execute(
                f"UPDATE {table_name} SET data = $2::jsonb, updated_at = NOW() WHERE id = $1",
                key,
                data,
            )
            return True

    async def get(self, projection: str, key: str) -> dict[str, Any] | None:
        """Get a single projection record by key."""
        await self._ensure_table(projection)
        key = pg_safe(key)
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

    async def scan_fields(
        self,
        projection: str,
        fields: Sequence[str],
        *,
        filters: Mapping[str, str | Sequence[str]] | None = None,
        order_by: str | None = None,
    ) -> list[tuple[str, Mapping[str, JsonValue]]]:
        """Selected fields of every matching document (syn_domain.projection_scan)."""
        from syn_adapters.projection_stores.postgres_scan import scan_fields

        await self._ensure_table(projection)
        return await scan_fields(
            await self._get_pool(),
            self._table_name(projection),
            fields,
            filters,
            order_by,
            lean_ready=projection in self._lean_tables,
        )

    async def newest_per_group(
        self,
        projection: str,
        *,
        group_field: str,
        timestamp_field: str,
        fields: Sequence[str],
        filters: Mapping[str, str | Sequence[str]] | None = None,
        flag_field: str | None = None,
    ) -> dict[str, Mapping[str, JsonValue]]:
        """Newest document per group, by instant, in one statement (projection_newest)."""
        from syn_adapters.projection_stores.postgres_scan import newest_per_group

        await self._ensure_table(projection)
        return await newest_per_group(
            await self._get_pool(),
            self._table_name(projection),
            group_field=group_field,
            timestamp_field=timestamp_field,
            fields=fields,
            filters=filters,
            flag_field=flag_field,
            lean_ready=projection in self._lean_tables,
        )

    async def count_by(
        self,
        projection: str,
        fields: Sequence[str],
        *,
        filters: Mapping[str, str | Sequence[str]] | None = None,
    ) -> list[tuple[GroupKey, int]]:
        """Matching documents counted per group of ``fields`` (syn_domain.projection_count)."""
        from syn_adapters.projection_stores.postgres_scan import count_by

        await self._ensure_table(projection)
        return await count_by(
            await self._get_pool(),
            self._table_name(projection),
            fields,
            filters,
            lean_ready=projection in self._lean_tables,
        )

    async def page_keys(self, projection: str, query: PageQuery) -> Page[str]:
        """One page of keys, its total and facets, in one query (syn_domain.projection_page)."""
        from syn_adapters.projection_stores.postgres_page_keys import page_keys

        await self._ensure_table(projection)
        return await page_keys(
            await self._get_pool(),
            self._table_name(projection),
            query,
            lean_ready=projection in self._lean_tables,
        )

    async def get_many(self, projection: str, keys: Sequence[str]) -> dict[str, ProjectionRecord]:
        """The whole documents stored under ``keys``, by key."""
        from syn_adapters.projection_stores.postgres_scan import get_many

        await self._ensure_table(projection)
        return await get_many(await self._get_pool(), self._table_name(projection), keys)

    async def page_in_sql(
        self, projection: str, request: SqlPageRequest, decide: Decide
    ) -> SqlPage:
        """One list page, its total and its facets, in one snapshot (projection_scan)."""
        from syn_adapters.projection_stores.postgres_page import page_in_sql

        await self._ensure_table(projection)
        return await page_in_sql(
            await self._get_pool(),
            self._table_name(projection),
            request,
            decide,
            lean_ready=projection in self._lean_tables,
        )

    async def count(self, projection: str, filters: dict[str, str] | None = None) -> int:
        """Count records with the same filter semantics `query` uses."""
        from syn_adapters.projection_stores.postgres_query_builder import build_count_query

        await self._ensure_table(projection)
        pool = await self._get_pool()
        query, params = build_count_query(self._table_name(projection), filters)
        async with pool.acquire() as conn:
            return int(await conn.fetchval(query, *params) or 0)

    async def get_by_prefix(self, projection: str, prefix: str) -> list[tuple[str, dict[str, Any]]]:
        """Get all records whose key starts with the given prefix."""
        await self._ensure_table(projection)
        prefix = pg_safe(prefix)
        pool = await self._get_pool()
        table_name = self._table_name(projection)

        # Escape LIKE meta-characters to prevent injection
        safe_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT id, data FROM {table_name} WHERE id LIKE $1 || '%%' ESCAPE '\\' LIMIT 10",
                safe_prefix,
            )
            return [(row["id"], self._deserialize(row["data"])) for row in rows]

    async def delete(self, projection: str, key: str) -> None:
        """Delete a projection record."""
        await self._ensure_table(projection)
        key = pg_safe(key)
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
        for build in list(self._index_builds):
            # A cancelled build leaves an INVALID index; the next start rebuilds it.
            build.cancel()
        if self._index_builds:
            await asyncio.gather(*self._index_builds, return_exceptions=True)
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._initialized_tables.clear()
