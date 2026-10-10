"""What agents shipped over a rolling window, against the window before it.

Feeds the Overview's "Shipped by agents" block: five tiles, each a window
total, the total of the window before it, a delta and one value per UTC day.

WHERE EACH NUMBER COMES FROM. Lane 2 and read models only; nothing here loads
an aggregate or reads the event store.

- **Commits**: distinct commit shas in the ``git_commit`` observations of
  ``agent_events`` that carry an ``execution_id``. Those rows are written by
  the workspace's post-commit hook through the engine, so each one is a commit
  an agent made inside an execution. Rows from the push webhook
  (``session_id = github_delivery:*``) carry no execution and are not
  counted: a push to a watched repo is not proof an agent wrote it. A sha is
  counted once, on the UTC day it was first seen; an amend or rebase writes a
  new sha and is a new commit. A row with no sha in any spelling is skipped.
- **Repos touched**: distinct ``owner/name`` slugs of the repositories the
  committing executions cloned, from the ``workflow_executions`` read model
  (``repos``, ADR-058). The commit row's own ``repo`` is the directory name,
  not the slug, so it cannot answer this.
- **PRs opened, PRs merged, merge rate**: UNAVAILABLE. No store persists PR
  outcomes: ``pull_request`` webhooks and Events API polls feed the trigger
  pipeline, which keeps dedup keys and fired triggers, never the PR; and an
  execution records a PR number only on a failing phase's branch observation
  (#1513); tracked in #1852. They are reported with ``reason`` set and every number ``None``,
  never as zero. The tile maths below is complete and tested, so a PR read
  model plugs straight in.

WHY NO PROJECTION. The commit read is one statement over ``git_commit`` rows
in the two windows (``idx_events_type (event_type, time DESC)``), so it costs
the commits in 2 x days, not the telemetry; attribution is one keyed read of
``workflow_executions`` for the executions that committed. Neither grows with
the number of executions, so a daily rollup would add a replay surface and buy
nothing at the scale the north star names.

THE DAY IS A UTC DAY: the window is ``days`` UTC calendar days ending today,
inclusive, and an observation belongs to the UTC day its ``time`` falls in
(the same contract as the contribution heatmap, #1371).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_shared.events import GIT_COMMIT

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    import asyncpg

    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
        WorkflowExecutionSummary,
    )

SHIPPED_WINDOW_DAYS: frozenset[int] = frozenset({7, 14, 30})
"""The window lengths the block offers."""

BY_WORKFLOW_LIMIT = 10
"""How many workflows ``by_workflow`` lists, most commits first."""

PR_OUTCOMES_NOT_PERSISTED = (
    "PR outcomes are not persisted: pull_request webhooks and Events API polls "
    "only feed the trigger pipeline (dedup keys and fired triggers), and an "
    "execution records a PR number only on a failing phase's branch observation "
    "(#1513). No read model holds PRs opened or merged (#1852)."
)

COMMITS_SOURCE = "agent_events: git_commit observations with an execution_id, distinct sha"
REPOS_SOURCE = "workflow_executions.repos of the executions that committed"
PRS_SOURCE = "none persisted"


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

    A previous window of zero has no relative change: nothing to something is
    ``"new"`` and nothing to nothing is ``"0%"``, never a division by zero.
    """
    if previous_total == 0:
        return (None, "new") if total > 0 else (0.0, "0%")
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
    """Relative change, None when the previous window was zero."""
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


def _window_rates(
    opened: ShippedCountTile, merged: ShippedCountTile
) -> tuple[float | None, float | None] | None:
    """(current, previous) rates, or None when either count is unmeasured."""
    counts = (opened.total, opened.previous_total, merged.total, merged.previous_total)
    if any(c is None for c in counts):
        return None
    o, po, m, pm = (c or 0 for c in counts)
    return _rate(m, o), _rate(pm, po)


def merge_rate_tile(opened: ShippedCountTile, merged: ShippedCountTile) -> ShippedRateTile:
    """merged / opened over the window, as a percent; delta in points.

    Unavailable whenever either side is: a rate over a missing count would be
    a number nobody measured.
    """
    source = f"prs_merged / prs_opened ({opened.source})"
    rates = _window_rates(opened, merged)
    if rates is None:
        return ShippedRateTile(
            source=source, reason=opened.reason or merged.reason or "PR counts unavailable"
        )
    total, previous = rates
    delta = None if total is None or previous is None else round(total - previous, 2)
    merged_by_day = {p.day: p.value for p in merged.series}
    return ShippedRateTile(
        source=source,
        total=total,
        previous_total=previous,
        delta=delta,
        delta_display=None if delta is None else format_points_delta(delta),
        total_display=None if total is None else format_percent(total),
        series=tuple(
            RatePoint(p.day, _rate(merged_by_day.get(p.day, 0), p.value)) for p in opened.series
        ),
    )


# =============================================================================
# Inputs
# =============================================================================


@dataclass(frozen=True)
class CommitSighting:
    """One commit an agent made: its sha, the execution, its first UTC day."""

    sha: str
    execution_id: str
    day: date


class CommitSightingSource(Protocol):
    """Commits agents made in ``[since, until)``, one per sha, first sighting."""

    async def sightings(self, since: datetime, until: datetime) -> list[CommitSighting]: ...


class ExecutionAttributionSource(Protocol):
    """The ``workflow_executions`` rows of the given executions, keyed by id."""

    async def by_ids(
        self, execution_ids: Sequence[str]
    ) -> Mapping[str, WorkflowExecutionSummary]: ...


# =============================================================================
# Result
# =============================================================================


@dataclass(frozen=True)
class ShippedWorkflow:
    """One workflow's share of the current window."""

    workflow_id: str
    workflow_name: str
    commits: int
    repos_touched: int


@dataclass(frozen=True)
class ShippedMetrics:
    """The five tiles over one window, with what they were measured from."""

    window: ShippedWindow
    workflow_id: str | None
    commits: ShippedCountTile
    prs_opened: ShippedCountTile
    prs_merged: ShippedCountTile
    merge_rate: ShippedRateTile
    repos_touched: ShippedCountTile
    repos: tuple[str, ...]
    """The distinct repos touched in the current window, ``owner/name``, sorted."""
    by_workflow: tuple[ShippedWorkflow, ...] | None
    """Top workflows by commits; None when the request is filtered to one."""
    commits_without_workflow: int = 0
    """Current-window commits whose execution the read model has no row for.

    Counted in ``commits`` (an execution made them) but in no workflow, so the
    ``by_workflow`` rows can sum to less than the tile.
    """
    unavailable: tuple[str, ...] = field(default=())
    """Names of the tiles that could not be measured."""


def _first_sightings(sightings: Iterable[CommitSighting]) -> list[CommitSighting]:
    """One sighting per sha, the earliest day. The store already does this;
    repeating it here keeps the count honest for any source."""
    first: dict[str, CommitSighting] = {}
    for s in sightings:
        seen = first.get(s.sha)
        if seen is None or s.day < seen.day:
            first[s.sha] = s
    return list(first.values())


def _repo_slugs(summary: WorkflowExecutionSummary | None) -> set[str]:
    if summary is None:
        return set()
    slugs: set[str] = set()
    for value in summary.repos:
        try:
            slugs.add(RepositoryRef.parse(value).slug)
        except ValueError:
            continue
    return slugs


def _by_workflow(
    current: Sequence[CommitSighting], summaries: Mapping[str, WorkflowExecutionSummary]
) -> tuple[ShippedWorkflow, ...]:
    commits: dict[str, int] = defaultdict(int)
    repos: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str] = {}
    for s in current:
        summary = summaries.get(s.execution_id)
        if summary is None:
            continue
        commits[summary.workflow_id] += 1
        repos[summary.workflow_id] |= _repo_slugs(summary)
        names[summary.workflow_id] = summary.workflow_name
    ranked = sorted(commits, key=lambda wf: (-commits[wf], wf))[:BY_WORKFLOW_LIMIT]
    return tuple(
        ShippedWorkflow(
            workflow_id=wf,
            workflow_name=names[wf],
            commits=commits[wf],
            repos_touched=len(repos[wf]),
        )
        for wf in ranked
    )


def build_shipped_metrics(
    window: ShippedWindow,
    sightings: Iterable[CommitSighting],
    summaries: Mapping[str, WorkflowExecutionSummary],
    workflow_id: str | None = None,
) -> ShippedMetrics:
    """Every tile of the block from the commits agents made in both windows."""
    commits = [
        s
        for s in _first_sightings(sightings)
        if window.is_current(s.day) or window.is_previous(s.day)
    ]
    if workflow_id is not None:
        commits = [
            s
            for s in commits
            if (summary := summaries.get(s.execution_id)) is not None
            and summary.workflow_id == workflow_id
        ]

    commits_per_day: dict[date, int] = defaultdict(int)
    repos_per_day: dict[date, set[str]] = defaultdict(set)
    for s in commits:
        commits_per_day[s.day] += 1
        repos_per_day[s.day] |= _repo_slugs(summaries.get(s.execution_id))

    repos_tile = distinct_tile(window, repos_per_day, DeltaUnit.COUNT, REPOS_SOURCE)
    current = [s for s in commits if window.is_current(s.day)]
    prs_opened = ShippedCountTile.unavailable(
        DeltaUnit.PERCENT, PR_OUTCOMES_NOT_PERSISTED, PRS_SOURCE
    )
    prs_merged = ShippedCountTile.unavailable(
        DeltaUnit.PERCENT, PR_OUTCOMES_NOT_PERSISTED, PRS_SOURCE
    )
    return ShippedMetrics(
        window=window,
        workflow_id=workflow_id,
        commits=count_tile(window, commits_per_day, DeltaUnit.PERCENT, COMMITS_SOURCE),
        prs_opened=prs_opened,
        prs_merged=prs_merged,
        merge_rate=merge_rate_tile(prs_opened, prs_merged),
        repos_touched=repos_tile,
        repos=tuple(
            sorted(set().union(*(v for d, v in repos_per_day.items() if window.is_current(d))))
        ),
        by_workflow=None if workflow_id is not None else _by_workflow(current, summaries),
        commits_without_workflow=sum(1 for s in current if s.execution_id not in summaries),
        unavailable=("prs_opened", "prs_merged", "merge_rate"),
    )


# =============================================================================
# Stores
# =============================================================================

# One row per sha: the first git_commit observation of it in the range. The sha
# is read in every spelling the timeline converter reads (GitFacts in
# syn_adapters.projections.session_tools_converters): v2 events nest it under
# ``git``, legacy ones spread it over the top level and ``context``, and the
# push webhook writes ``commit_hash`` (excluded anyway: it has no execution).
# The day is the UTC day of ``time``, spelled as the heatmap spells it (#1371).
_SIGHTINGS_QUERY = """
SELECT DISTINCT ON (sha) sha, execution_id, (time AT TIME ZONE 'UTC')::date AS day
FROM (
    SELECT time, execution_id,
        COALESCE(
            NULLIF(data->'git'->>'sha', ''),
            NULLIF(data->>'sha', ''),
            NULLIF(data->'context'->>'sha', ''),
            NULLIF(data->>'commit_hash', '')
        ) AS sha
    FROM agent_events
    WHERE event_type = $1
      AND execution_id IS NOT NULL
      AND execution_id <> ''
      AND time >= $2
      AND time < $3
) commits
WHERE sha IS NOT NULL
ORDER BY sha, time
"""


class TimescaleCommitSightings:
    """``CommitSightingSource`` over ``agent_events`` (Lane 2)."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def sightings(self, since: datetime, until: datetime) -> list[CommitSighting]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_SIGHTINGS_QUERY, GIT_COMMIT, since, until)
        return [
            CommitSighting(sha=str(r["sha"]), execution_id=str(r["execution_id"]), day=r["day"])
            for r in rows
        ]


def utc_today() -> date:
    return datetime.now(UTC).date()


class ShippedMetricsQueryService:
    """Answers the "Shipped by agents" block from Lane 2 and read models."""

    def __init__(
        self,
        sightings: CommitSightingSource,
        executions: ExecutionAttributionSource,
        today: Callable[[], date] = utc_today,
    ) -> None:
        self._sightings = sightings
        self._executions = executions
        self._today = today

    async def shipped(self, days: int = 14, workflow_id: str | None = None) -> ShippedMetrics:
        window = ShippedWindow.ending(self._today(), days)
        sightings = await self._sightings.sightings(window.since, window.until)
        summaries = await self._executions.by_ids(sorted({s.execution_id for s in sightings}))
        return build_shipped_metrics(window, sightings, summaries, workflow_id)
