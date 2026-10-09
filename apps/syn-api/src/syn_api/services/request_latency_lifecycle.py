"""Start and stop the durable request latency recorder (ADR-075).

Best-effort, like every Lane 2 writer, and never on the startup path: readying
``api_request_latency`` runs in a supervised background task that retries with
backoff until it succeeds, each attempt bounded by
``request_latency_io_timeout_s``. A database that is down or slow at boot
delays recording, not the API; until recording starts every sample is a counted
drop, which ``GET /observability/latency`` reports.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from syn_adapters.request_latency import (
    RequestLatencyRecorder,
    ensure_request_latency_schema,
    request_latency_recorder,
)
from syn_api._wiring import get_event_store_instance
from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import asyncpg

logger = logging.getLogger(__name__)

#: First and largest wait between attempts to ready the table.
BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 60.0

_supervisor: asyncio.Task[None] | None = None


async def _ready_pool(timeout_s: float) -> asyncpg.Pool | None:
    """The observability pool once ``api_request_latency`` exists on it, else None."""
    store = get_event_store_instance()
    pool = store.pool
    if pool is None:
        logger.warning("request latency: observability pool not open yet")
        return None
    async with asyncio.timeout(timeout_s), pool.acquire() as conn:
        ready = await ensure_request_latency_schema(
            conn,  # type: ignore[arg-type]  # asyncpg PoolConnectionProxy is compatible with Connection
            skip_auto_create=store.skip_auto_create,
        )
    if not ready:
        logger.warning(
            "request latency: api_request_latency does not exist and "
            "SYN_SKIP_AUTO_CREATE_TABLES forbids creating it; apply migration 009"
        )
        return None
    return pool


async def supervise(
    ready: Callable[[float], Awaitable[asyncpg.Pool | None]] = _ready_pool,
    *,
    recorder: RequestLatencyRecorder = request_latency_recorder,
    backoff_start_s: float = BACKOFF_START_S,
    backoff_max_s: float = BACKOFF_MAX_S,
) -> None:
    """Retry readying the table with exponential backoff, then start the recorder."""
    timeout_s = get_settings().request_latency_io_timeout_s
    delay = backoff_start_s
    while True:
        try:
            pool = await ready(timeout_s)
        except Exception:
            logger.warning("request latency: table not ready, retrying", exc_info=True)
            pool = None
        if pool is not None:
            recorder.configure(io_timeout_s=timeout_s)
            recorder.start(pool)
            logger.info("request latency recorder started")
            return
        await asyncio.sleep(delay)
        delay = min(delay * 2, backoff_max_s)


async def start_request_latency() -> None:
    """Launch the supervisor; returns at once."""
    global _supervisor
    if _supervisor is None or _supervisor.done():
        _supervisor = asyncio.create_task(supervise(), name="request-latency-supervisor")


async def stop_request_latency() -> None:
    """Stop retrying, then write what is buffered within the shutdown deadline."""
    global _supervisor
    task, _supervisor = _supervisor, None
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    try:
        await request_latency_recorder.stop(
            timeout_s=get_settings().request_latency_shutdown_timeout_s
        )
    except Exception:
        logger.warning("request latency recorder did not stop cleanly", exc_info=True)
