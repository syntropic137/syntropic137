"""Samples reach a real TimescaleDB and come back as exact percentiles (ADR-073).

Uses the shared ``test_infrastructure`` fixture (ADR-034): test-stack on port
15432, else testcontainers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def pool(test_infrastructure):
    from syn_adapters.events import AgentEventStore
    from syn_adapters.request_latency import ensure_request_latency_schema

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    assert store.pool is not None
    async with store.pool.acquire() as conn:
        assert await ensure_request_latency_schema(conn, skip_auto_create=False)
        # Idempotent: a second startup readies nothing new and does not fail.
        assert await ensure_request_latency_schema(conn, skip_auto_create=False)
    yield store.pool
    await store.close()


async def test_recorded_samples_come_back_as_exact_percentiles(pool) -> None:
    from syn_adapters.request_latency import (
        RequestLatencyRecorder,
        RequestSample,
        latency_by_route,
    )

    route = f"/it/{uuid4().hex}/{{item_id}}"
    now = datetime.now(UTC)
    recorder = RequestLatencyRecorder(batch_size=40, flush_interval_s=60)
    recorder.start(pool)
    for ms in range(1, 101):  # 1..100 ms
        recorder.offer(RequestSample(now, "GET", route, 200, float(ms), uuid4().hex))
    recorder.offer(RequestSample(now - timedelta(days=2), "GET", route, 200, 9_999.0, "old"))
    await recorder.stop()
    assert recorder.counters().written == 101

    (row,) = await latency_by_route(pool, since=now - timedelta(hours=1), route=route)

    assert (row.method, row.route, row.count) == ("GET", route, 100)
    # percentile_cont interpolates: p50 of 1..100 is 50.5, p99 is 99.01.
    assert row.p50_ms == pytest.approx(50.5)
    assert row.p99_ms == pytest.approx(99.01)
    assert row.max_ms == 100.0
    (wider,) = await latency_by_route(pool, since=now - timedelta(days=3), route=route)
    assert wider.count == 101
