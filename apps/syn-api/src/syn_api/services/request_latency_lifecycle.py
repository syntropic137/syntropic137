"""Start and stop the durable request latency recorder (ADR-075).

Best-effort, like every Lane 2 writer: if the table cannot be readied the API
serves anyway and the recorder counts every sample as dropped, which
``GET /observability/latency`` reports.
"""

from __future__ import annotations

import logging

from syn_adapters.request_latency import ensure_request_latency_schema, request_latency_recorder
from syn_api._wiring import get_event_store_instance

logger = logging.getLogger(__name__)


async def start_request_latency() -> None:
    """Ready ``api_request_latency`` on the observability pool and start draining into it."""
    try:
        store = get_event_store_instance()
        pool = store.pool
        if pool is None:
            logger.warning("request latency not recorded: observability pool not open")
            return
        async with pool.acquire() as conn:
            ready = await ensure_request_latency_schema(
                conn,  # type: ignore[arg-type]  # asyncpg PoolConnectionProxy is compatible with Connection
                skip_auto_create=store.skip_auto_create,
            )
        if not ready:
            logger.warning("request latency not recorded: api_request_latency does not exist")
            return
        request_latency_recorder.start(pool)
        logger.info("request latency recorder started")
    except Exception:
        logger.warning("request latency recorder not started", exc_info=True)


async def stop_request_latency() -> None:
    """Write what is buffered and stop. Before the observability pool closes."""
    try:
        await request_latency_recorder.stop()
    except Exception:
        logger.warning("request latency recorder did not stop cleanly", exc_info=True)
