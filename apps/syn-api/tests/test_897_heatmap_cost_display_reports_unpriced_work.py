"""The contribution heatmap's dollar figures say when work could not be priced (#897).

The heatmap query already counts ``unpriced_tokens`` per day into each bucket's
``breakdown``, but the dashboard formatted ``breakdown["cost_usd"]`` itself, so a
day or a window with unpriced model groups read as a complete dollar figure.
The API now renders ``cost_display`` per day and ``total_cost_display`` for the
window with ``format_cost``.

These go THROUGH the endpoint with only the heatmap service function stubbed,
so the response construction is under test: a display built correctly and then
dropped by the constructor fails here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from syn_api.types import ContributionHeatmapResponse


@dataclass(frozen=True)
class _Day:
    """A bucket shaped as ``TimescaleHeatmapQuery`` returns it."""

    date: str
    breakdown: dict[str, float]
    count: float = 1.0
    failed: int = 0


def _day(day: str, *, cost_usd: float, unpriced_tokens: float) -> _Day:
    return _Day(
        date=day,
        breakdown={
            "sessions": 1.0,
            "executions": 1.0,
            "commits": 0.0,
            "cost_usd": cost_usd,
            "tokens": 100.0,
            "unpriced_tokens": unpriced_tokens,
        },
    )


@dataclass(frozen=True)
class _Heatmap:
    """The ``get_contribution_heatmap`` result, as the handler's ``to_dict`` gives it."""

    days: list[_Day]
    metric: str = "sessions"
    start_date: str = "2026-11-01"
    end_date: str = "2026-11-03"
    total: float = 0.0
    filter: dict[str, str | None] = field(default_factory=dict)


PRICED = _day("2026-11-01", cost_usd=1.25, unpriced_tokens=0.0)
PARTIAL = _day("2026-11-02", cost_usd=0.5, unpriced_tokens=1_700.0)
UNPRICED = _day("2026-11-03", cost_usd=0.0, unpriced_tokens=40.0)


async def _heatmap(
    monkeypatch: pytest.MonkeyPatch, days: list[_Day]
) -> ContributionHeatmapResponse:
    from syn_api.routes import insights
    from syn_api.types import ContributionHeatmapResponse

    async def _stub(**_: object):
        return asdict(_Heatmap(days=days))

    monkeypatch.setattr(insights, "get_contribution_heatmap", _stub)
    response = await insights.get_contribution_heatmap_endpoint(
        organization_id=None,
        system_id=None,
        repo_id=None,
        start_date=None,
        end_date=None,
        metric="sessions",
    )
    assert isinstance(response, ContributionHeatmapResponse)
    return response


@pytest.mark.unit
class TestHeatmapCostDisplay:
    @pytest.mark.asyncio
    async def test_a_fully_priced_window_renders_plain_dollars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = await _heatmap(monkeypatch, [PRICED])

        assert [d.cost_display for d in response.days] == ["$1.25"]
        assert response.total_cost_display == "$1.25"

    @pytest.mark.asyncio
    async def test_a_partly_unpriced_day_is_a_lower_bound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = await _heatmap(monkeypatch, [PRICED, PARTIAL])

        assert [d.cost_display for d in response.days] == ["$1.25", ">=$0.50 (partial)"]
        assert response.total_cost_display == ">=$1.75 (partial)"

    @pytest.mark.asyncio
    async def test_an_all_unpriced_day_is_unpriced_not_zero_dollars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = await _heatmap(monkeypatch, [UNPRICED])

        assert [d.cost_display for d in response.days] == ["unpriced"]
        assert response.total_cost_display == "unpriced"

    @pytest.mark.asyncio
    async def test_one_unpriced_day_makes_the_window_partial(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = await _heatmap(monkeypatch, [PRICED, UNPRICED])

        assert [d.cost_display for d in response.days] == ["$1.25", "unpriced"]
        assert response.total_cost_display == ">=$1.25 (partial)"

    @pytest.mark.asyncio
    async def test_an_empty_window_costs_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = await _heatmap(monkeypatch, [])

        assert response.days == []
        assert response.total_cost_display == "$0.00"
