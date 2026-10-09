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
    from collections.abc import AsyncIterator

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


def _timed_app(recorder: RequestLatencyRecorder) -> object:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse, StreamingResponse

    app = FastAPI()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("application failure")

    @app.get("/own-id")
    async def own_id() -> JSONResponse:
        return JSONResponse({"ok": True}, headers={"X-Request-ID": "set-by-the-app"})

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        async def body() -> AsyncIterator[bytes]:
            yield b"first"
            # The client is still reading; the sample must already exist.
            assert isinstance(recorder, _Capture)
            yield f"samples-before-close={len(recorder.samples)}".encode()

        return StreamingResponse(body())

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(
        RequestTimingMiddleware,
        slow_request_ms=60_000,
        aggregator=RequestTimingAggregator(),
        recorder=recorder,
    )
    return app


async def test_an_unhandled_500_carries_its_request_id_and_is_recorded() -> None:
    recorder = _Capture()
    app = _timed_app(recorder)
    transport = ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]  # an ASGI app
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/boom")

    (sample,) = recorder.samples
    assert response.status_code == 500
    assert response.headers["x-request-id"] == sample.request_id
    assert (sample.route, sample.status) == ("/boom", 500)


async def test_the_application_exception_still_propagates() -> None:
    app = _timed_app(_Capture())
    transport = ASGITransport(app=app)  # type: ignore[arg-type]  # an ASGI app
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        with pytest.raises(RuntimeError, match="application failure"):
            await client.get("/boom")


class _Raising(RequestLatencyRecorder):
    def offer(self, sample: RequestSample) -> None:
        raise RuntimeError("telemetry broke")


async def test_a_raising_recorder_never_fails_the_request() -> None:
    app = _timed_app(_Raising())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:  # type: ignore[arg-type]  # an ASGI app
        response = await client.get("/ok")
        with pytest.raises(RuntimeError, match="application failure"):
            await client.get("/boom")  # the APP's exception, not the recorder's

    assert response.status_code == 200
    assert "x-request-id" in response.headers


async def test_an_app_supplied_request_id_is_replaced_not_duplicated() -> None:
    recorder = _Capture()
    app = _timed_app(recorder)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:  # type: ignore[arg-type]  # an ASGI app
        response = await client.get("/own-id")

    assert response.headers.get_list("x-request-id") == [recorder.samples[0].request_id]


async def test_a_stream_is_recorded_when_it_answers_not_when_it_closes() -> None:
    recorder = _Capture()
    app = _timed_app(recorder)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:  # type: ignore[arg-type]  # an ASGI app
        response = await client.get("/stream")

    assert response.text.endswith("samples-before-close=1")
    assert len(recorder.samples) == 1


async def test_a_startup_gate_503_is_timed_and_carries_a_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The timing middleware wraps the gate in the real app, not the other way round."""
    from syn_api.main import create_app

    recorder = _Capture()
    monkeypatch.setattr("syn_api.middleware.request_timing.request_latency_recorder", recorder)
    app = create_app()
    app.state.startup_gate._phase = "starting"  # pyright: ignore[reportPrivateUsage]  # hold the gate shut

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get("/evals")

    assert response.status_code == 503
    (sample,) = recorder.samples
    assert response.headers["x-request-id"] == sample.request_id
    assert sample.status == 503


class _SchemaConn:
    def __init__(self) -> None:
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    async def execute(self, statement: str) -> str:
        return "OK"

    async def fetchval(self, query: str, *args: object) -> bool:
        return True


class _SchemaPool:
    """asyncpg's acquire(timeout)/release(conn, timeout), able to stall either."""

    def __init__(self, *, acquire_hangs: bool = False, release_hangs: bool = False) -> None:
        self.acquire_hangs = acquire_hangs
        self.release_hangs = release_hangs
        self.conns: list[_SchemaConn] = []

    async def acquire(self, *, timeout: float | None = None) -> _SchemaConn:
        import asyncio

        if self.acquire_hangs:
            await asyncio.wait_for(asyncio.Event().wait(), timeout=timeout)
        conn = _SchemaConn()
        self.conns.append(conn)
        return conn

    async def release(self, connection: _SchemaConn, *, timeout: float | None = None) -> None:
        import asyncio

        if self.release_hangs and not connection.terminated:
            await asyncio.shield(asyncio.Event().wait())  # a stalled reset, as asyncpg shields it


def _store_with(pool: _SchemaPool) -> object:
    class _Store:
        skip_auto_create = False

    store = _Store()
    store.pool = pool  # type: ignore[attr-defined]  # the double's one attribute the code reads
    return store


async def test_readying_the_table_is_bounded_by_its_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BLOCKER: a stalled acquire at startup used to wait forever."""
    import asyncio

    from syn_api.services import request_latency_lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle, "get_event_store_instance", lambda: _store_with(_SchemaPool(acquire_hangs=True))
    )
    async with asyncio.timeout(2):
        with pytest.raises(TimeoutError):
            await lifecycle._ready_pool(0.05)  # pyright: ignore[reportPrivateUsage]  # the attempt itself


async def test_a_stalled_release_after_the_schema_attempt_terminates_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BLOCKER: the release asyncpg shields used to outlive the attempt and block pool.close()."""
    import asyncio

    from syn_api.services import request_latency_lifecycle as lifecycle

    pool = _SchemaPool(release_hangs=True)
    monkeypatch.setattr(lifecycle, "get_event_store_instance", lambda: _store_with(pool))
    loop = asyncio.get_running_loop()
    started = loop.time()
    async with asyncio.timeout(2):
        ready = await lifecycle._ready_pool(0.05)  # pyright: ignore[reportPrivateUsage]  # the attempt itself

    assert ready is pool
    assert loop.time() - started < 0.5
    (conn,) = pool.conns
    assert conn.terminated


async def test_supervisor_teardown_is_bounded_even_if_the_task_will_not_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from syn_api.services import request_latency_lifecycle as lifecycle

    class _Settings:
        request_latency_io_timeout_s = 0.05
        request_latency_shutdown_timeout_s = 0.05

    refusing = True

    async def stubborn() -> None:
        while True:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                if not refusing:
                    raise
                # Refuses to end: the worst case teardown must survive.

    task = asyncio.create_task(stubborn())
    await asyncio.sleep(0)  # let it reach its loop before anyone cancels it
    monkeypatch.setattr(lifecycle, "get_settings", lambda: _Settings())
    monkeypatch.setattr(lifecycle, "_supervisor", task)
    async with asyncio.timeout(2):
        await lifecycle.stop_request_latency()

    assert not task.done()  # it was abandoned, not awaited forever
    refusing = False
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_failed_schema_init_is_retried_until_recording_starts() -> None:
    """A transient failure at boot used to disable recording until restart."""
    from syn_api.services.request_latency_lifecycle import supervise

    attempts: list[float] = []
    pool = object()

    async def flaky(timeout_s: float) -> object | None:
        attempts.append(timeout_s)
        if len(attempts) == 1:
            raise ConnectionError("db not up yet")
        return None if len(attempts) == 2 else pool

    recorder = RequestLatencyRecorder()
    await supervise(flaky, recorder=recorder, backoff_start_s=0.001, backoff_max_s=0.002)  # type: ignore[arg-type]  # a pool double

    assert len(attempts) == 3
    assert recorder.running
    await recorder.stop(timeout_s=1)


async def test_the_frameworks_own_error_response_is_kept_and_stamped() -> None:
    """SHOULD FIX 1: the timing layer replaced a custom 500 body and headers with its own."""
    from fastapi.responses import JSONResponse
    from starlette.requests import Request  # noqa: TC002  # FastAPI reads the annotation

    from syn_api.main import create_app

    app = create_app()

    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"error": "custom"}, status_code=500, headers={"X-Custom": "kept"})

    app.add_exception_handler(Exception, handler)

    @app.get("/__boom")
    async def boom() -> None:
        raise RuntimeError("application failure")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/__boom")

    assert response.status_code == 500
    assert response.json() == {"error": "custom"}
    assert response.headers["x-custom"] == "kept"
    assert len(response.headers.get_list("x-request-id")) == 1


async def test_the_debug_traceback_page_is_kept_and_stamped() -> None:
    from syn_api.main import create_app

    app = create_app()
    app.debug = True

    @app.get("/__boom")
    async def boom() -> None:
        raise RuntimeError("application failure")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/__boom", headers={"accept": "text/html"})

    assert response.status_code == 500
    assert "RuntimeError" in response.text  # Starlette's traceback, not a bare 500
    assert "x-request-id" in response.headers
