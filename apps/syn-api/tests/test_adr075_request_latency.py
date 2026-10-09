"""Every request is recorded by route template, off the request path (ADR-075).

The middleware hands each answered request to the recorder and returns: no
I/O, no await. These pin what is recorded (template, never the raw path), that
the id reaches the client, the overhead, and the read route's shape.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_adapters.request_latency import RequestLatencyRecorder, RequestSample, RouteLatency
from syn_api.middleware.request_timing import RequestTimingAggregator, RequestTimingMiddleware

if TYPE_CHECKING:
    from starlette.types import Message, Receive, Scope, Send

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


class _Capture(RequestLatencyRecorder):
    """The recorder as the middleware sees it, keeping what it was offered."""

    def __init__(self) -> None:
        super().__init__()
        self.samples: list[RequestSample] = []

    def offer(self, sample: RequestSample) -> None:
        self.samples.append(sample)


async def test_a_request_is_recorded_by_template_with_its_id_returned() -> None:
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/items/{item_id}")
    async def get_item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    recorder = _Capture()
    app.add_middleware(
        RequestTimingMiddleware,
        slow_request_ms=60_000,
        aggregator=RequestTimingAggregator(),
        recorder=recorder,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        ok = await client.get("/items/secret-token-123?q=also-secret")
        missing = await client.get("/nope/secret-path")

    first, second = recorder.samples
    assert (first.method, first.route, first.status) == ("GET", "/items/{item_id}", 200)
    assert ok.headers["x-request-id"] == first.request_id
    assert (second.route, second.status) == ("<unmatched>", 404)
    assert missing.headers["x-request-id"] == second.request_id
    # The raw path, its ids and its query never reach a sample.
    assert "secret" not in repr(recorder.samples)
    assert first.duration_ms >= 0


async def test_the_middleware_adds_well_under_a_millisecond_per_request() -> None:
    """In-process: the same trivial ASGI app, with and without the middleware."""

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        return None

    scope: Scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
    recorder = RequestLatencyRecorder(capacity=10)  # not started: every offer is a counted drop
    wrapped = RequestTimingMiddleware(
        app, slow_request_ms=60_000, aggregator=RequestTimingAggregator(), recorder=recorder
    )
    n = 5_000

    async def per_request_ms(target: object) -> float:
        call = target.__call__  # type: ignore[attr-defined]  # both are ASGI callables
        started = time.perf_counter()
        for _ in range(n):
            await call(dict(scope), receive, send)
        return (time.perf_counter() - started) * 1000 / n

    await per_request_ms(wrapped)  # warm
    bare = await per_request_ms(app)
    timed = await per_request_ms(wrapped)
    overhead = timed - bare
    print(f"\nmiddleware overhead: {overhead * 1000:.1f} us/request")
    assert overhead < 1.0, f"{overhead:.3f} ms per request"
    assert recorder.counters().dropped >= n


async def test_the_latency_route_serves_typed_percentiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.main import create_app
    from syn_api.types import RequestLatencyResponse

    asked: list[tuple[datetime, str | None]] = []

    async def fake_latency(
        pool: object, *, since: datetime, route: str | None = None
    ) -> list[RouteLatency]:
        asked.append((since, route))
        return [RouteLatency("GET", "/evals", 12, 40.0, 900.0, 24_500.0, 26_000.0)]

    class _Store:
        pool = object()

    monkeypatch.setattr("syn_adapters.request_latency.latency_by_route", fake_latency)
    monkeypatch.setattr("syn_api._wiring.get_event_store_instance", lambda: _Store())

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        response = await c.get("/observability/latency", params={"window": "7d", "route": "/evals"})

    assert response.status_code == 200, response.text
    body = RequestLatencyResponse.model_validate(response.json())
    assert body.available
    assert body.window == "7d"
    (row,) = body.routes
    assert (row.route, row.count, row.p99_ms, row.p99_display) == ("/evals", 12, 24_500.0, "24.5 s")
    since, route = asked[0]
    assert route == "/evals"
    assert 6.9 < (datetime.now(UTC) - since).total_seconds() / 86_400 < 7.1


async def test_the_latency_route_says_when_the_store_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.main import create_app

    class _Store:
        pool = None

    monkeypatch.setattr("syn_api._wiring.get_event_store_instance", lambda: _Store())
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        response = await c.get("/observability/latency")

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["routes"] == []
    bad = await AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t").get(
        "/observability/latency", params={"window": "1y"}
    )
    assert bad.status_code == 422
