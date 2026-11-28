"""The latency gates' estimator: still fails a regression, no longer fails a stall.

Runs without a database: a fake clock and a fake request stand in for the API,
so each case is the exact timing it names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from .latency_gate import RUNS_PER_ROUND, measure, over_budget, p95_of, report

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _Endpoint:
    name: str
    path: str
    budget_ms: float
    params: Mapping[str, str] = field(default_factory=dict)


METRICS = _Endpoint("/metrics", "/metrics", 100.0)
HEATMAP = _Endpoint("/insights/contribution-heatmap", "/insights/contribution-heatmap", 150.0)


class _FakeApi:
    """Each request advances a fake clock by the time its timing table gives."""

    def __init__(self, timing: dict[str, list[float]]) -> None:
        self._timing = timing  # path -> milliseconds for each timed call, in order
        self._served: dict[str, int] = {}
        self.now = 0.0
        self.calls: list[str] = []

    def clock(self) -> float:
        return self.now

    async def request(self, path: str, params: Mapping[str, str]) -> None:
        del params
        index = self._served.get(path, 0)
        self._served[path] = index + 1
        self.calls.append(path)
        series = self._timing[path]
        self.now += series[min(index, len(series) - 1)] / 1000


def _steady(ms: float, n: int) -> list[float]:
    return [ms] * n


async def _gate(api: _FakeApi, *endpoints: _Endpoint) -> list[str]:
    measured = await measure(api.request, endpoints, warmup=0, clock=api.clock)
    return over_budget(endpoints, measured)


async def test_a_whole_history_read_still_fails_every_round() -> None:
    """The regression the gate exists for: /metrics back to a ~500ms whole-history read."""
    api = _FakeApi({"/metrics": _steady(500.0, 200)})
    assert await _gate(api, METRICS) == ["/metrics"]


async def test_one_stalled_round_does_not_fail_a_fast_endpoint() -> None:
    """Two 150ms stalls in one round make that round's p95 150ms: one bad round, not a fail."""
    first_round = [60.0] * (RUNS_PER_ROUND - 2) + [150.0, 150.0]
    api = _FakeApi({"/metrics": first_round + _steady(60.0, 2 * RUNS_PER_ROUND)})
    # What the old single-round estimator read off the same first round: a fail.
    assert p95_of(first_round) == 150.0
    assert await _gate(api, METRICS) == []


async def test_two_slow_rounds_fail() -> None:
    """Sustained slowness, not a stall: the median round is over budget."""
    slow = _steady(120.0, RUNS_PER_ROUND)
    api = _FakeApi({"/metrics": slow + slow + _steady(60.0, RUNS_PER_ROUND)})
    assert await _gate(api, METRICS) == ["/metrics"]


async def test_endpoints_take_turns_request_by_request() -> None:
    api = _FakeApi({"/metrics": _steady(10.0, 200), HEATMAP.path: _steady(10.0, 200)})
    await _gate(api, METRICS, HEATMAP)
    assert api.calls[:4] == ["/metrics", HEATMAP.path, "/metrics", HEATMAP.path]


async def test_the_report_carries_every_round_and_the_median() -> None:
    api = _FakeApi({"/metrics": _steady(42.0, 200)})
    measured = await measure(api.request, [METRICS], warmup=0, clock=api.clock)
    table = report("latency gate", [METRICS], measured)
    assert table.count("42.0") == 4  # three rounds and the median
    assert "budget   100 ms" in table
