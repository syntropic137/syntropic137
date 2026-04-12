"""Shared database pool for wiring dependencies.

See ADR-060: Restart-safe trigger deduplication.

Provides a lazily-initialized asyncpg pool that can be shared across
the dedup adapter, poller cursor store, and other components that
need direct Postgres access outside the event store.
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def init_shared_db_pool() -> asyncpg.Pool | None:
    """Initialize the shared database pool (call during startup).

    Returns the pool, or None if the DB URL is not configured.
    """
    from syn_shared.settings import get_settings

    global _pool

    settings = get_settings()
    db_url = settings.syn_observability_db_url
    if not db_url:
        logger.info("No SYN_OBSERVABILITY_DB_URL — shared DB pool disabled")
        return None

    async with _pool_lock:
        if _pool is not None:
            return _pool
        _pool = await asyncpg.create_pool(
            str(db_url),
            min_size=2,
            max_size=5,
        )
        logger.info("Shared DB pool initialized for dedup and cursor store")
        return _pool


def get_shared_db_pool() -> asyncpg.Pool | None:
    """Get the shared pool (must be initialized first via init_shared_db_pool)."""
    return _pool


async def close_shared_db_pool() -> None:
    """Close the shared pool (call during shutdown)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Shared DB pool closed")
