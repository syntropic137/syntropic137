"""Per-route request timing must aggregate by route TEMPLATE, not raw path (#1070).

The middleware records durations after each request; the aggregator is what an
operator would actually consume (p50/p95/p99 + count). The trap: recording
against the raw path instead of the matched route template still produces a
snapshot with plausible-looking numbers, but every distinct id fragments the
data into its own single-sample bucket - the exact failure mode #1070
complains about ("`/executions/{id}` aggregates" is the issue's own wording).
A test that only checks the middleware ran, or only checks the aggregator's
math in isolation, would pass under that regression. These drive real FastAPI
routing over HTTP and read back through the aggregator - the consuming side -
so a route-template regression fails here.
"""

from __future__ import annotations

import pytest

from syn_api.middleware.request_timing import RequestTimingAggregator, RequestTimingMiddleware


async def _make_client(aggregator: RequestTimingAggregator):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()

    @app.get("/items/{item_id}")
    async def get_item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    app.add_middleware(RequestTimingMiddleware, aggregator=aggregator)

    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_distinct_ids_on_the_same_route_share_one_bucket() -> None:
    """This is the assertion a raw-path implementation cannot pass.

    Recording under `/items/apple`, `/items/banana`, `/items/cherry` as three
    literal strings would leave three one-sample buckets and no key matching
    the template below - `snapshot()` would report nothing for it.
    """
    aggregator = RequestTimingAggregator()
    client = await _make_client(aggregator)

    async with client:
        for item_id in ("apple", "banana", "cherry"):
            response = await client.get(f"/items/{item_id}")
            assert response.status_code == 200

    snapshot = aggregator.snapshot("/items/{item_id}")

    assert snapshot is not None
    assert snapshot.count == 3
    assert aggregator.known_routes() == ["/items/{item_id}"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_snapshot_reports_a_positive_duration_for_a_request_that_happened() -> None:
    """A fixture that could only exist post-fix.

    A snapshot for a route no test setup populated directly - it exists only
    because the middleware actually recorded a real, timed request.
    """
    aggregator = RequestTimingAggregator()
    client = await _make_client(aggregator)

    async with client:
        response = await client.get("/items/only-one")
        assert response.status_code == 200

    snapshot = aggregator.snapshot("/items/{item_id}")

    assert snapshot is not None
    assert snapshot.count == 1
    assert snapshot.p50_ms >= 0
    assert snapshot.p95_ms >= snapshot.p50_ms
    assert snapshot.p99_ms >= snapshot.p95_ms


@pytest.mark.unit
@pytest.mark.asyncio
async def test_an_unmatched_path_does_not_pollute_the_route_template_bucket() -> None:
    """A 404 has no matched route.

    It must not be silently folded into a real template's statistics, and it
    must not be silently dropped from observability either - it lands under
    its own raw-path key.
    """
    aggregator = RequestTimingAggregator()
    client = await _make_client(aggregator)

    async with client:
        response = await client.get("/does-not-exist")
        assert response.status_code == 404

    assert aggregator.snapshot("/items/{item_id}") is None
    assert aggregator.snapshot("/does-not-exist") is not None


@pytest.mark.unit
def test_snapshot_of_an_unrecorded_route_is_none() -> None:
    aggregator = RequestTimingAggregator()

    assert aggregator.snapshot("/never/hit") is None
    assert aggregator.known_routes() == []


@pytest.mark.unit
def test_the_window_evicts_the_oldest_sample_rather_than_growing_unbounded() -> None:
    aggregator = RequestTimingAggregator(window_size=3)

    for duration_ms in (10.0, 20.0, 30.0, 40.0):
        aggregator.record("/items/{item_id}", duration_ms)

    snapshot = aggregator.snapshot("/items/{item_id}")

    assert snapshot is not None
    assert snapshot.count == 3
    # 10.0 (the oldest) must have been evicted, or the p50 could not be 30.0.
    assert snapshot.p50_ms == 30.0
