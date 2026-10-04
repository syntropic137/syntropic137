"""A stalled request must be attributable from the API's own output (#1583).

Every dashboard client stalled for about six minutes and nothing could say
whether the API, its database pool, or the tunnel in front of it held the
requests. These tests read the two things an operator reads - the slow-request
log line and the ``/health`` payload - through real HTTP, because a duration
computed correctly and dropped at the logger call, or a pool gauge computed
correctly and dropped at ``HealthResponse``, passes every test that inspects
the middleware or the pool directly.

The pool is the real ``_InstrumentedPool`` with asyncpg's own acquire stubbed
out to block until released: no database is needed to see a caller waiting,
and the wait is a value that could only reach the log through this change.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import pytest
from asyncpg.pool import Pool
from httpx import ASGITransport, AsyncClient

from syn_adapters import postgres_pool
from syn_adapters.postgres_pool import _InstrumentedPool
from syn_api.middleware.request_timing import RequestTimingAggregator, RequestTimingMiddleware

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

_LOGGER = "syn_api.middleware.request_timing"
_THRESHOLD_MS = 150
_SLOW_S = 0.3
_EXECUTION_ID = "exec-7f3a9c41-not-a-template"
_SECRET = "ghs_TOKEN_THAT_MUST_NOT_BE_LOGGED"

pytestmark = pytest.mark.unit


class _BlockingAcquire:
    """Stands in for asyncpg's PoolAcquireContext: blocks until *gate* opens."""

    def __init__(self, gate: asyncio.Event) -> None:
        self._gate = gate

    async def _connection(self) -> str:
        await self._gate.wait()
        return "connection"

    async def __aenter__(self) -> str:
        return await self._connection()

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def __await__(self):
        return self._connection().__await__()


@pytest.fixture
def blocking_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[_InstrumentedPool, asyncio.Event]]:
    """A registered instrumented pool: 4 open, 1 idle, max 7; acquire waits on the gate."""
    gate = asyncio.Event()
    monkeypatch.setattr(Pool, "acquire", lambda _self, **_kw: _BlockingAcquire(gate))
    monkeypatch.setattr(Pool, "get_size", lambda _self: 4)
    monkeypatch.setattr(Pool, "get_idle_size", lambda _self: 1)
    monkeypatch.setattr(Pool, "get_max_size", lambda _self: 7)
    monkeypatch.setattr(Pool, "is_closing", lambda _self: False)
    # Skip asyncpg's connecting __init__; only the instrumentation is under test.
    pool = object.__new__(_InstrumentedPool)
    pool.name = "projections"
    pool.waiting = 0
    postgres_pool._live_pools.add(pool)
    try:
        yield pool, gate
    finally:
        postgres_pool._live_pools.discard(pool)


def _app(
    pool: _InstrumentedPool | None = None,
    gate: asyncio.Event | None = None,
    *,
    threshold_ms: int = _THRESHOLD_MS,
) -> FastAPI:
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/executions/{execution_id}")
    async def slow(execution_id: str) -> dict[str, str]:
        await asyncio.sleep(_SLOW_S)
        return {"execution_id": execution_id}

    @app.get("/executions/{execution_id}/fails")
    async def slow_then_raises(execution_id: str) -> dict[str, str]:
        await asyncio.sleep(_SLOW_S)
        raise RuntimeError(f"handler failed for {execution_id}")

    @app.get("/fast")
    async def fast() -> dict[str, str]:
        return {}

    @app.get("/waits-for-pool")
    async def waits_for_pool() -> dict[str, str]:
        assert pool is not None and gate is not None
        asyncio.get_running_loop().call_later(_SLOW_S, gate.set)
        async with pool.acquire():
            pass
        return {}

    app.add_middleware(
        RequestTimingMiddleware,
        aggregator=RequestTimingAggregator(),
        slow_request_ms=threshold_ms,
    )
    return app


async def _get(app: FastAPI, url: str, **kwargs: object) -> int:
    # raise_app_exceptions=False: the client sees the 500 a real server sends,
    # rather than the transport re-raising the handler's exception.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(url, **kwargs)  # type: ignore[arg-type]  # test passthrough
    return response.status_code


def _slow_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER]


def _field(line: str, key: str) -> str:
    return next(part.split("=", 1)[1] for part in line.split() if part.startswith(f"{key}="))


async def test_a_slow_request_is_logged_by_template_with_status_and_duration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    status = await _get(
        _app(),
        f"/executions/{_EXECUTION_ID}?token={_SECRET}",
        headers={"Authorization": f"Bearer {_SECRET}"},
    )

    assert status == 200
    [line] = _slow_lines(caplog)
    assert _field(line, "method") == "GET"
    assert _field(line, "route") == "/executions/{execution_id}"
    assert _field(line, "status") == "200"
    assert int(_field(line, "duration_ms")) >= _SLOW_S * 1000
    assert _field(line, "pool_wait_ms") == "0"
    # The raw path, the query string and the headers never reach the log.
    assert _EXECUTION_ID not in caplog.text
    assert _SECRET not in caplog.text


async def test_a_slow_request_that_raises_is_logged_with_the_500_the_client_got(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The exception crosses this middleware before the outer handler answers 500."""
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    status = await _get(_app(), f"/executions/{_EXECUTION_ID}/fails?token={_SECRET}")

    assert status == 500
    [line] = _slow_lines(caplog)
    assert _field(line, "route") == "/executions/{execution_id}/fails"
    assert _field(line, "status") == "500"
    assert int(_field(line, "duration_ms")) >= _SLOW_S * 1000
    assert _EXECUTION_ID not in "\n".join(_slow_lines(caplog))
    assert _SECRET not in caplog.text


async def test_a_fast_request_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)

    assert await _get(_app(), "/fast") == 200

    assert _slow_lines(caplog) == []


async def test_an_unmatched_path_is_logged_without_the_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 404 has no template; falling back to the raw path would leak what it held."""
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    assert await _get(_app(threshold_ms=0), f"/nowhere/{_SECRET}") == 404

    [line] = _slow_lines(caplog)
    assert _field(line, "route") == "<unmatched>"
    assert _field(line, "status") == "404"
    assert _SECRET not in caplog.text


async def test_time_spent_waiting_for_a_pool_connection_is_logged(
    caplog: pytest.LogCaptureFixture,
    blocking_pool: tuple[_InstrumentedPool, asyncio.Event],
) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    pool, gate = blocking_pool

    assert await _get(_app(pool, gate), "/waits-for-pool") == 200

    [line] = _slow_lines(caplog)
    assert _field(line, "route") == "/waits-for-pool"
    assert int(_field(line, "pool_wait_ms")) >= _SLOW_S * 1000 * 0.9
    assert pool.waiting == 0


async def test_health_reports_every_open_pool_with_its_waiters(
    blocking_pool: tuple[_InstrumentedPool, asyncio.Event],
) -> None:
    """Read while a caller is genuinely blocked in acquire(), so waiting=1 is earned."""
    from syn_api.main import create_app

    pool, gate = blocking_pool
    waiter = asyncio.create_task(pool.acquire().__aenter__())
    await asyncio.sleep(0)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=create_app()), base_url="http://test"
        ) as client:
            response = await client.get("/health")
    finally:
        gate.set()
        await waiter

    assert response.status_code == 200, response.text
    assert json.loads(response.text)["db_pools"] == [
        {"name": "projections", "size": 4, "max_size": 7, "in_use": 3, "waiting": 1}
    ]


async def test_create_app_takes_the_threshold_from_settings(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The setting must reach the middleware the real app installs."""
    from syn_api.main import create_app
    from syn_shared.settings import get_settings

    monkeypatch.setenv("SLOW_REQUEST_LOG_THRESHOLD_MS", "20")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        app = create_app()
    finally:
        monkeypatch.delenv("SLOW_REQUEST_LOG_THRESHOLD_MS")
        get_settings.cache_clear()  # type: ignore[attr-defined]

    @app.get("/sleeps-50ms")
    async def sleeps() -> dict[str, str]:
        await asyncio.sleep(0.05)
        return {}

    caplog.set_level(logging.WARNING, logger=_LOGGER)
    assert await _get(app, "/sleeps-50ms") == 200

    [line] = _slow_lines(caplog)
    assert _field(line, "route") == "/sleeps-50ms"
