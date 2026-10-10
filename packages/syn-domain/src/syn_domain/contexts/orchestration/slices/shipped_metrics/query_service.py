"""What agents shipped over a rolling window, against the window before it.

Feeds the Overview's "Shipped by agents" block: five tiles, each a window
total, the total of the window before it, a delta and one value per UTC day.

READS ONLY THE ROLLUP. Every number comes from ``shipped_daily`` rows (one per
UTC day x repository x workflow, see ``ledger``): at most ``2 x days`` days of
them, so a request costs what it returns and nothing grows with telemetry.
The facts behind the rows are recorded once, at ingestion, and only for work
an execution produced:

- **Commits**: distinct shas from the run's ``git_commit`` hook events.
- **PRs opened**: PRs a run created with a successful ``gh pr create``
  (``gh_pr_create``), counted on the day they were created.
- **PRs merged**: merges of those PRs, from ``pull_request`` (closed, merged)
  events the GitHub pipeline ingests, counted on the day they merged. A merge
  of a PR no run created never counts.
- **Merge rate**: a cohort conversion: of the run PRs OPENED in the window,
  the share merged by now. Bounded 0-100 by construction.
- **Repos touched**: distinct repositories with any of the above in the
  window, never a sum over days.

A short in-process cache keyed by (UTC day, days, workflow) with request
coalescing sits in front: concurrent Overview loads share one rollup read.

THE DAY IS A UTC DAY: the window is ``days`` UTC calendar days ending today,
inclusive (the same contract as the contribution heatmap, #1371).
"""

from __future__ import annotations

import asyncio
import time as monotonic_clock
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from syn_domain.contexts.orchestration._shared.shipped_ledger import (
        ShippedDayRow,
        ShippedLedger,
    )

SHIPPED_WINDOW_DAYS: frozenset[int] = frozenset({7, 14, 30})
"""The window lengths the block offers."""

BY_WORKFLOW_LIMIT = 10
"""How many workflows ``by_workflow`` lists."""

CACHE_SECONDS = 30.0
"""How long one answer is served before the rollup is read again."""

COMMITS_SOURCE = "shipped_daily.commits: distinct shas from runs' git_commit hook events"
PRS_OPENED_SOURCE = "shipped_daily.prs_opened: PRs created by a run's successful `gh pr create`"
PRS_MERGED_SOURCE = (
    "shipped_daily.prs_merged: merges of run PRs, from pull_request closed+merged events"
)
MERGE_RATE_SOURCE = "shipped_daily: prs_opened_merged / prs_opened (cohort of PRs opened)"
REPOS_SOURCE = "shipped_daily: distinct repositories with a commit or run PR"


class DeltaUnit(StrEnum):
    """What a tile's ``delta_display`` is expressed in."""

    PERCENT = "percent"
    """Change relative to the previous window: "+38%"."""
    POINTS = "points"
    """Difference of two percentages: "+5 pts"."""
    COUNT = "count"
    """Difference of two counts: "+3"."""


# =============================================================================
# Window
# =============================================================================


@dataclass(frozen=True)
class ShippedWindow:
    """``days`` UTC days ending ``end`` inclusive, and the ``days`` before them."""

    days: int
    start: date
    end: date
    previous_start: date
    previous_end: date

    @classmethod
    def ending(cls, today: date, days: int) -> ShippedWindow:
        """The window of ``days`` UTC days whose last day is ``today``."""
        if days not in SHIPPED_WINDOW_DAYS:
            allowed = ", ".join(str(d) for d in sorted(SHIPPED_WINDOW_DAYS))
            raise ValueError(f"days must be one of {allowed}, got {days}")
        start = today - timedelta(days=days - 1)
        previous_end = start - timedelta(days=1)
        return cls(
            days=days,
            start=start,
            end=today,
            previous_start=previous_end - timedelta(days=days - 1),
            previous_end=previous_end,
        )

    @property
    def since(self) -> datetime:
        """The first instant either window covers (UTC midnight)."""
        return datetime.combine(self.previous_start, time.min, tzinfo=UTC)

    @property
    def until(self) -> datetime:
        """The first instant after the current window (exclusive bound)."""
        return datetime.combine(self.end + timedelta(days=1), time.min, tzinfo=UTC)

    def current_days(self) -> list[date]:
        """Every day of the current window, oldest first."""
        return [self.start + timedelta(days=i) for i in range(self.days)]

    def is_current(self, day: date) -> bool:
        return self.start <= day <= self.end

    def is_previous(self, day: date) -> bool:
        return self.previous_start <= day <= self.previous_end


# =============================================================================
# Delta formatting
# =============================================================================


def _round_half_up(value: float) -> int:
    return int(Decimal(repr(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _signed(value: int, suffix: str) -> str:
    return f"+{value}{suffix}" if value > 0 else f"{value}{suffix}"


def format_percent_delta(total: int, previous_total: int) -> tuple[float | None, str]:
    """Relative change and its display: ``(37.99, "+38%")``.

    A previous window of zero has no relative change, so the percent is None
    whenever ``previous_total`` is 0 (including 0 to 0); only the display
    differs: nothing to something is ``"new"``, nothing to nothing ``"0%"``.
    """
    if previous_total == 0:
        return (None, "new") if total > 0 else (None, "0%")
    percent = (total - previous_total) / previous_total * 100
    return round(percent, 2), _signed(_round_half_up(percent), "%")


def format_points_delta(points: float) -> str:
    """A percentage-point difference: ``"+5 pts"``, ``"-3 pts"``, ``"0 pts"``."""
    return _signed(_round_half_up(points), " pts")


def format_count_delta(delta: int) -> str:
    """A count difference: ``"+3"``, ``"-2"``, ``"0"``."""
    return _signed(delta, "")


def format_count(value: int) -> str:
    return f"{value:,}"


def format_percent(value: float) -> str:
    return f"{_round_half_up(value)}%"


# =============================================================================
# Tiles
# =============================================================================


@dataclass(frozen=True)
class CountPoint:
    day: date
    value: int


@dataclass(frozen=True)
class RatePoint:
    day: date
    value: float | None
    """Percent, or None on a day with no denominator."""


@dataclass(frozen=True)
class ShippedCountTile:
    """A count over the window. Every number is None when ``reason`` is set."""

    delta_unit: DeltaUnit
    source: str
    total: int | None = None
    previous_total: int | None = None
    delta: int | None = None
    """``total - previous_total``."""
    delta_percent: float | None = None
    """Relative change; None whenever the previous window was zero, 0 to 0 included."""
    delta_display: str | None = None
    total_display: str | None = None
    series: tuple[CountPoint, ...] = ()
    reason: str | None = None

    @classmethod
    def unavailable(cls, unit: DeltaUnit, reason: str, source: str) -> ShippedCountTile:
        return cls(delta_unit=unit, source=source, reason=reason)

    @classmethod
    def measured(
        cls,
        window: ShippedWindow,
        *,
        per_day: Mapping[date, int],
        total: int,
        previous_total: int,
        unit: DeltaUnit,
        source: str,
    ) -> ShippedCountTile:
        delta = total - previous_total
        percent, percent_display = format_percent_delta(total, previous_total)
        return cls(
            delta_unit=unit,
            source=source,
            total=total,
            previous_total=previous_total,
            delta=delta,
            delta_percent=percent,
            delta_display=percent_display
            if unit is DeltaUnit.PERCENT
            else format_count_delta(delta),
            total_display=format_count(total),
            series=tuple(CountPoint(d, per_day.get(d, 0)) for d in window.current_days()),
        )


@dataclass(frozen=True)
class ShippedRateTile:
    """A percentage over the window; ``delta`` is in points."""

    source: str
    total: float | None = None
    previous_total: float | None = None
    delta: float | None = None
    delta_display: str | None = None
    total_display: str | None = None
    series: tuple[RatePoint, ...] = ()
    reason: str | None = None
    delta_unit: DeltaUnit = DeltaUnit.POINTS


def count_tile(
    window: ShippedWindow, per_day: Mapping[date, int], unit: DeltaUnit, source: str
) -> ShippedCountTile:
    """A summed count: the window total is the sum of its days."""
    return ShippedCountTile.measured(
        window,
        per_day=per_day,
        total=sum(v for d, v in per_day.items() if window.is_current(d)),
        previous_total=sum(v for d, v in per_day.items() if window.is_previous(d)),
        unit=unit,
        source=source,
    )


def distinct_tile(
    window: ShippedWindow, per_day: Mapping[date, set[str]], unit: DeltaUnit, source: str
) -> ShippedCountTile:
    """A distinct count: the window total is the size of the union, not a sum.

    A repo touched on ten days is one repo touched, so summing the daily series
    would overstate it by the number of days it was active.
    """
    current: set[str] = set()
    previous: set[str] = set()
    for day, values in per_day.items():
        if window.is_current(day):
            current |= values
        elif window.is_previous(day):
            previous |= values
    return ShippedCountTile.measured(
        window,
        per_day={d: len(v) for d, v in per_day.items()},
        total=len(current),
        previous_total=len(previous),
        unit=unit,
        source=source,
    )


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator * 100, 2)


@dataclass(frozen=True)
class _Cohort:
    """Run PRs opened per day, and how many of them have merged since."""

    opened: Mapping[date, int]
    merged: Mapping[date, int]

    def total(self, window: ShippedWindow, previous: bool) -> tuple[int, int]:
        def keep(d: date) -> bool:
            return window.is_previous(d) if previous else window.is_current(d)

        return (
            sum(v for d, v in self.merged.items() if keep(d)),
            sum(v for d, v in self.opened.items() if keep(d)),
        )


def merge_rate_tile(window: ShippedWindow, cohort: _Cohort) -> ShippedRateTile:
    """Of the run PRs opened in the window, the share merged by now (percent).

    A cohort conversion, so it can never exceed 100: the numerator is a subset
    of the denominator. The previous window's rate is the same question asked
    of ITS cohort, as of now. Null when no PR was opened: no data is not 0%.
    """
    total = _rate(*cohort.total(window, previous=False))
    previous = _rate(*cohort.total(window, previous=True))
    delta = None if total is None or previous is None else round(total - previous, 2)
    return ShippedRateTile(
        source=MERGE_RATE_SOURCE,
        total=total,
        previous_total=previous,
        delta=delta,
        delta_display=None if delta is None else format_points_delta(delta),
        total_display=None if total is None else format_percent(total),
        series=tuple(
            RatePoint(d, _rate(cohort.merged.get(d, 0), cohort.opened.get(d, 0)))
            for d in window.current_days()
        ),
    )


# =============================================================================
# Result
# =============================================================================


@dataclass(frozen=True)
class ShippedWorkflow:
    """One workflow's share of the current window."""

    workflow_id: str
    name: str
    commits: int
    prs_opened: int
    prs_merged: int
    repos_touched: int


@dataclass(frozen=True)
class ShippedMetrics:
    """The five tiles over one window."""

    window: ShippedWindow
    workflow_id: str | None
    commits: ShippedCountTile
    prs_opened: ShippedCountTile
    prs_merged: ShippedCountTile
    merge_rate: ShippedRateTile
    repos_touched: ShippedCountTile
    repos: tuple[str, ...]
    """The distinct repos touched in the current window, ``owner/name``, sorted."""
    by_workflow: tuple[ShippedWorkflow, ...]
    """Top workflows by commits, then PRs merged; empty when filtered to one."""
    unavailable: tuple[str, ...] = field(default=())
    """Names of the tiles that could not be measured."""


@dataclass
class _Totals:
    name: str = ""
    commits: int = 0
    prs_opened: int = 0
    prs_merged: int = 0
    repos: set[str] = field(default_factory=set)


@dataclass
class _Days:
    """The rollup rows folded per day (and, for the current window, per workflow)."""

    commits: dict[date, int] = field(default_factory=lambda: defaultdict(int))
    opened: dict[date, int] = field(default_factory=lambda: defaultdict(int))
    merged: dict[date, int] = field(default_factory=lambda: defaultdict(int))
    opened_merged: dict[date, int] = field(default_factory=lambda: defaultdict(int))
    repos: dict[date, set[str]] = field(default_factory=lambda: defaultdict(set))
    workflows: dict[str, _Totals] = field(default_factory=dict)

    def add(self, window: ShippedWindow, row: ShippedDayRow) -> None:
        self.commits[row.day] += row.commits
        self.opened[row.day] += row.prs_opened
        self.merged[row.day] += row.prs_merged
        self.opened_merged[row.day] += row.prs_opened_merged
        if row.commits or row.prs_opened or row.prs_merged:
            self.repos[row.day].add(row.repository)
        if window.is_current(row.day):
            self._add_workflow(row)

    def _add_workflow(self, row: ShippedDayRow) -> None:
        totals = self.workflows.setdefault(row.workflow_id, _Totals())
        totals.name = row.workflow_name or totals.name
        totals.commits += row.commits
        totals.prs_opened += row.prs_opened
        totals.prs_merged += row.prs_merged
        if row.commits or row.prs_opened or row.prs_merged:
            totals.repos.add(row.repository)

    def by_workflow(self) -> tuple[ShippedWorkflow, ...]:
        w = self.workflows
        ranked = sorted(w, key=lambda k: (-w[k].commits, -w[k].prs_merged, k))
        return tuple(
            ShippedWorkflow(
                workflow_id=k,
                name=w[k].name,
                commits=w[k].commits,
                prs_opened=w[k].prs_opened,
                prs_merged=w[k].prs_merged,
                repos_touched=len(w[k].repos),
            )
            for k in ranked[:BY_WORKFLOW_LIMIT]
        )


def build_shipped_metrics(
    window: ShippedWindow, rows: Iterable[ShippedDayRow], workflow_id: str | None = None
) -> ShippedMetrics:
    """Every tile of the block from the rollup rows of both windows."""
    days = _Days()
    for row in rows:
        if window.is_current(row.day) or window.is_previous(row.day):
            days.add(window, row)
    current_repos = set().union(*(v for d, v in days.repos.items() if window.is_current(d)))
    return ShippedMetrics(
        window=window,
        workflow_id=workflow_id,
        commits=count_tile(window, days.commits, DeltaUnit.PERCENT, COMMITS_SOURCE),
        prs_opened=count_tile(window, days.opened, DeltaUnit.PERCENT, PRS_OPENED_SOURCE),
        prs_merged=count_tile(window, days.merged, DeltaUnit.PERCENT, PRS_MERGED_SOURCE),
        merge_rate=merge_rate_tile(window, _Cohort(days.opened, days.opened_merged)),
        repos_touched=distinct_tile(window, days.repos, DeltaUnit.COUNT, REPOS_SOURCE),
        repos=tuple(sorted(current_repos)),
        by_workflow=() if workflow_id is not None else days.by_workflow(),
    )


# =============================================================================
# Service: rollup read behind a short, coalescing cache
# =============================================================================


def utc_today() -> date:
    return datetime.now(UTC).date()


type _CacheKey = tuple[date, int, str | None]


@dataclass(frozen=True)
class _Cached:
    expires_at: float
    metrics: ShippedMetrics


class ShippedMetricsQueryService:
    """Answers the "Shipped by agents" block from the shipped rollup only.

    One instance per process: the cache and the in-flight map live on it.
    Concurrent requests for the same key share one rollup read (coalescing);
    an answer is reused for ``cache_seconds``, and never across a UTC day.
    A failed read is not cached.
    """

    def __init__(
        self,
        ledger: ShippedLedger,
        today: Callable[[], date] = utc_today,
        clock: Callable[[], float] = monotonic_clock.monotonic,
        cache_seconds: float = CACHE_SECONDS,
    ) -> None:
        self._ledger = ledger
        self._today = today
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._cache: dict[_CacheKey, _Cached] = {}
        self._in_flight: dict[_CacheKey, asyncio.Future[ShippedMetrics]] = {}

    async def shipped(self, days: int = 14, workflow_id: str | None = None) -> ShippedMetrics:
        window = ShippedWindow.ending(self._today(), days)
        key: _CacheKey = (window.end, days, workflow_id)
        cached = self._cache.get(key)
        if cached is not None and cached.expires_at > self._clock():
            return cached.metrics
        pending = self._in_flight.get(key)
        if pending is not None:
            return await asyncio.shield(pending)
        future: asyncio.Future[ShippedMetrics] = asyncio.get_running_loop().create_future()
        self._in_flight[key] = future
        try:
            rows = await self._ledger.daily(window.previous_start, window.end, workflow_id)
            metrics = build_shipped_metrics(window, rows, workflow_id)
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # retrieved here, so an unawaited future does not warn
            raise
        finally:
            self._in_flight.pop(key, None)
        self._cache = {k: v for k, v in self._cache.items() if k[0] == window.end}
        self._cache[key] = _Cached(self._clock() + self._cache_seconds, metrics)
        future.set_result(metrics)
        return metrics
