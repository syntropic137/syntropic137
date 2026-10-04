"""A startup slower than the health window must not fail the health check (#1575).

The incident: the #1558 usage-rollup backfill ran inside the FastAPI lifespan
for ~2 minutes, uvicorn served nothing until it returned, the compose health
check gave up, and the gateway (``depends_on: service_healthy``) was never
started. These drive the REAL app - ``create_app()``'s lifespan, middleware and
``/health`` route - with ``lifecycle.startup`` replaced by a fake backfill that
does not finish until the test lets it, i.e. longer than any window.

Without the gate, entering the lifespan blocks until that backfill ends, so the
first test times out instead of reading ``starting``.
"""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

import syn_api.services.lifecycle as lifecycle
import syn_api.startup_gate as startup_gate
from syn_api.main import create_app
from syn_api.startup_gate import StartupGate
from syn_api.types import Err, HealthResponse, LifecycleError, Ok

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI

pytestmark = pytest.mark.unit

#: Short enough to keep the suite fast; the fake backfill outlasts it by as long
#: as the test likes.
_GRACE = 0.05

#: Production seconds -> test seconds. The grace window is scaled by this, and
#: so is the compose health schedule, so the two keep their real proportions.
_SCALE = _GRACE / startup_gate.DEFAULT_GRACE_SECONDS

_COMPOSE = Path(__file__).resolve().parents[3] / "docker" / "docker-compose.syntropic137.yaml"


def _seconds(value: str) -> float:
    assert value.endswith("s"), f"unexpected compose duration {value!r}"
    return float(value[:-1])


@dataclass(frozen=True)
class _HealthSchedule:
    """The API's compose health check: when Docker probes, and when it gives up."""

    start_period: float
    interval: float
    retries: int

    @property
    def failure_window(self) -> float:
        """The latest a failing probe stops counting as 'still starting' - the
        point at which, in the incident, the API was declared unhealthy."""
        return self.start_period + self.interval * self.retries


def _api_health_schedule() -> _HealthSchedule:
    # Read from the shipped compose file, not restated, so a change to the
    # health check moves this test with it.
    check = yaml.safe_load(_COMPOSE.read_text())["services"]["api"]["healthcheck"]
    return _HealthSchedule(
        start_period=_seconds(check["start_period"]),
        interval=_seconds(check["interval"]),
        retries=int(check["retries"]),
    )


class _SlowBackfill:
    """A startup that blocks until released, as the production backfill did."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.terminated: list[int] = []

    async def startup(self, skip_validation: bool = False) -> Ok[dict]:
        self.started.set()
        await self.release.wait()
        return Ok({"mode": "full"})


async def _healthy() -> Ok[HealthResponse]:
    from syn_api.build_info import get_build_info

    return Ok(HealthResponse(status="healthy", mode="full", build=get_build_info()))


@pytest.fixture
def slow(monkeypatch: pytest.MonkeyPatch) -> _SlowBackfill:
    fake = _SlowBackfill()
    # A gate that gives up on a running startup terminates the process; record
    # that instead of letting it SIGTERM the test runner.
    monkeypatch.setattr(signal, "raise_signal", fake.terminated.append)
    monkeypatch.setattr(startup_gate, "DEFAULT_GRACE_SECONDS", _GRACE)
    monkeypatch.setattr(lifecycle, "startup", fake.startup)
    monkeypatch.setattr(lifecycle, "health_check", _healthy)

    async def _noop_shutdown() -> Ok[None]:
        return Ok(None)

    monkeypatch.setattr(lifecycle, "shutdown", _noop_shutdown)
    return fake


async def _serving(app: FastAPI) -> AsyncIterator[AsyncClient]:
    # Bounded: before #1575 this await is the whole backfill.
    ctx = app.router.lifespan_context(app)
    await asyncio.wait_for(ctx.__aenter__(), timeout=2)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        await ctx.__aexit__(None, None, None)


async def test_health_answers_starting_while_the_backfill_outlasts_the_window(
    slow: _SlowBackfill,
) -> None:
    """Probe /health on Docker's own schedule, scaled, until past the point
    where the incident's container was declared unhealthy - with the backfill
    still running the whole time - and only then let it finish."""
    schedule = _api_health_schedule()
    loop = asyncio.get_running_loop()
    began = loop.time()
    app = create_app()
    async for client in _serving(app):
        assert slow.started.is_set()
        # Every probe Docker would make up to one interval past the failure
        # window: start_period, then each interval through all the retries.
        probe = schedule.start_period
        probes = 0
        while probe <= schedule.failure_window + schedule.interval:
            await asyncio.sleep(max(0.0, began + probe * _SCALE - loop.time()))
            health = await client.get("/health")
            assert health.status_code == 200, f"probe at {probe:.0f}s (scaled)"
            assert health.json()["status"] == "starting", f"probe at {probe:.0f}s (scaled)"
            assert app.state.startup_gate.phase == "starting"
            probe += schedule.interval
            probes += 1
        assert probes > schedule.retries
        assert loop.time() - began > schedule.failure_window * _SCALE
        assert not slow.release.is_set() and not slow.terminated

        # Liveness is not readiness: nothing that reads the store is served.
        refused = await client.get("/workflows")
        assert refused.status_code == 503
        assert refused.headers["retry-after"]
        assert (await client.get("/version")).status_code == 200

        slow.release.set()
        for _ in range(100):
            if app.state.startup_gate.phase == "ready":
                break
            await asyncio.sleep(0.01)
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"
        assert (await client.get("/workflows")).status_code != 503
        assert not slow.terminated


async def test_a_startup_inside_the_window_never_shows_starting(slow: _SlowBackfill) -> None:
    slow.release.set()
    app = create_app()
    async for client in _serving(app):
        assert app.state.startup_gate.phase == "ready"
        assert (await client.get("/health")).json()["status"] == "healthy"


async def test_a_failure_inside_the_window_still_refuses_to_serve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing(skip_validation: bool = False) -> Err[LifecycleError]:
        return Err(LifecycleError.CONNECTION_FAILED, message="event store unreachable")

    monkeypatch.setattr(lifecycle, "startup", failing)
    app = create_app()
    with pytest.raises(RuntimeError, match="event store unreachable"):
        await app.router.lifespan_context(app).__aenter__()


async def test_a_failure_after_serving_began_terminates_instead_of_hiding() -> None:
    """A slow start is waited for; a failed one must not sit there 'starting'."""
    terminated = asyncio.Event()
    release = asyncio.Event()

    async def start() -> None:
        await release.wait()
        raise RuntimeError("backfill failed")

    gate = StartupGate(grace_seconds=_GRACE, on_late_failure=terminated.set)
    await asyncio.wait_for(gate.open(start), timeout=2)
    assert gate.phase == "starting"

    release.set()
    await asyncio.wait_for(terminated.wait(), timeout=1)
    assert gate.phase == "failed"
    assert gate.refuses("/workflows") and not gate.refuses("/health")


async def test_before_any_lifespan_the_gate_is_not_in_the_way() -> None:
    """ASGI transports in tests never run the lifespan; they must be served."""
    gate = StartupGate()
    assert gate.phase == "not_started"
    assert not gate.refuses("/workflows")
