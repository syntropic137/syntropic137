"""Tests for the "Shipped by agents" query: window maths, deltas, tiles, scenario."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)
from syn_domain.contexts.orchestration.slices.shipped_metrics import (
    MERGE_LOOKBACK_DAYS,
    CommitSighting,
    DeltaUnit,
    MergedPullRequest,
    RunPullRequest,
    ShippedMetricsQueryService,
    ShippedWindow,
    build_shipped_metrics,
    format_count_delta,
    format_percent_delta,
    format_points_delta,
)
from syn_domain.contexts.orchestration.slices.shipped_metrics.query_service import (
    count_tile,
    distinct_tile,
    merge_rate_tile,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from event_sourcing import ProjectionStore

    from syn_domain.pagination import ProjectionRecord

TODAY = date(2026, 10, 9)


def _summary(execution_id: str, workflow_id: str, repos: Sequence[str]) -> WorkflowExecutionSummary:
    return WorkflowExecutionSummary(
        workflow_execution_id=execution_id,
        workflow_id=workflow_id,
        workflow_name=workflow_id.upper(),
        status="completed",
        started_at=None,
        completed_at=None,
        completed_phases=1,
        total_phases=1,
        total_tokens=0,
        repos=tuple(repos),
    )


class _Sightings:
    def __init__(self, rows: list[CommitSighting]) -> None:
        self.rows = rows
        self.asked: tuple[datetime, datetime] | None = None

    async def sightings(self, since: datetime, until: datetime) -> list[CommitSighting]:
        self.asked = (since, until)
        return self.rows


class _PullRequests:
    def __init__(self, opened: list[RunPullRequest], merged: list[MergedPullRequest]) -> None:
        self._opened = opened
        self._merged = merged
        self.asked_opened: tuple[datetime, datetime] | None = None
        self.asked_merged: tuple[datetime, datetime] | None = None

    async def opened(self, since: datetime, until: datetime) -> list[RunPullRequest]:
        self.asked_opened = (since, until)
        return self._opened

    async def merged(self, since: datetime, until: datetime) -> list[MergedPullRequest]:
        self.asked_merged = (since, until)
        return self._merged


class _Executions:
    def __init__(self, rows: Mapping[str, WorkflowExecutionSummary]) -> None:
        self.rows = rows
        self.asked: list[str] = []

    async def by_ids(self, execution_ids: Sequence[str]) -> Mapping[str, WorkflowExecutionSummary]:
        self.asked = list(execution_ids)
        return {k: v for k, v in self.rows.items() if k in execution_ids}


@pytest.mark.unit
class TestWindow:
    def test_fourteen_days_end_today_inclusive(self) -> None:
        w = ShippedWindow.ending(TODAY, 14)
        assert (w.start, w.end) == (date(2026, 9, 26), TODAY)
        assert (w.previous_start, w.previous_end) == (date(2026, 9, 12), date(2026, 9, 25))
        assert len(w.current_days()) == 14
        assert w.current_days()[0] == w.start and w.current_days()[-1] == TODAY

    @pytest.mark.parametrize("days", [7, 14, 30])
    def test_windows_are_adjacent_and_equal_length(self, days: int) -> None:
        w = ShippedWindow.ending(TODAY, days)
        assert w.previous_end + timedelta(days=1) == w.start
        assert (w.previous_end - w.previous_start).days + 1 == days
        assert (w.end - w.start).days + 1 == days

    def test_bounds_are_utc_midnights_spanning_both_windows(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        assert w.since == datetime(2026, 9, 26, tzinfo=UTC)
        assert w.until == datetime(2026, 10, 10, tzinfo=UTC)

    @pytest.mark.parametrize("days", [0, 1, 13, 31, 90])
    def test_other_lengths_are_refused(self, days: int) -> None:
        with pytest.raises(ValueError, match="days must be one of 7, 14, 30"):
            ShippedWindow.ending(TODAY, days)


@pytest.mark.unit
class TestDeltaFormatting:
    @pytest.mark.parametrize(
        ("total", "previous", "display"),
        [
            (1204, 872, "+38%"),
            (73, 59, "+24%"),
            (61, 48, "+27%"),
            (50, 100, "-50%"),
            (10, 10, "0%"),
            (0, 0, "0%"),
            (5, 0, "new"),
            (0, 5, "-100%"),
            (201, 200, "+1%"),  # 0.5 rounds half up
        ],
    )
    def test_percent(self, total: int, previous: int, display: str) -> None:
        assert format_percent_delta(total, previous)[1] == display

    def test_percent_is_none_without_a_previous_window(self) -> None:
        assert format_percent_delta(5, 0)[0] is None
        assert format_percent_delta(1204, 872)[0] == pytest.approx(38.07, abs=0.01)

    @pytest.mark.parametrize(
        ("points", "display"),
        [(5.23, "+5 pts"), (2.2, "+2 pts"), (-3.6, "-4 pts"), (0.0, "0 pts"), (0.49, "0 pts")],
    )
    def test_points(self, points: float, display: str) -> None:
        assert format_points_delta(points) == display

    @pytest.mark.parametrize(("delta", "display"), [(3, "+3"), (-2, "-2"), (0, "0")])
    def test_count(self, delta: int, display: str) -> None:
        assert format_count_delta(delta) == display


@pytest.mark.unit
class TestTiles:
    def test_count_tile_sums_and_zero_fills_oldest_first(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        per_day = {TODAY: 3, w.start: 2, w.previous_end: 4}
        tile = count_tile(w, per_day, DeltaUnit.PERCENT, "test")
        assert (tile.total, tile.previous_total, tile.delta) == (5, 4, 1)
        assert tile.delta_display == "+25%"
        assert [p.value for p in tile.series] == [2, 0, 0, 0, 0, 0, 3]
        assert [p.day for p in tile.series] == w.current_days()

    def test_distinct_tile_counts_the_union_not_the_sum(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        per_day = {
            w.start: {"a/x", "a/y"},
            TODAY: {"a/x", "a/z"},
            w.previous_end: {"a/x"},
        }
        tile = distinct_tile(w, per_day, DeltaUnit.COUNT, "test")
        assert (tile.total, tile.previous_total, tile.delta_display) == (3, 1, "+2")
        assert tile.series[0].value == 2 and tile.series[-1].value == 2

    def test_merge_rate_is_merged_over_opened_in_points(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        opened = count_tile(w, {TODAY: 73, w.previous_end: 60}, DeltaUnit.PERCENT, "prs")
        merged = count_tile(w, {TODAY: 61, w.previous_end: 47}, DeltaUnit.PERCENT, "prs")
        rate = merge_rate_tile(opened, merged)
        assert rate.total == pytest.approx(83.56, abs=0.01)
        assert rate.previous_total == pytest.approx(78.33, abs=0.01)
        assert (rate.total_display, rate.delta_display) == ("84%", "+5 pts")
        assert rate.delta_unit is DeltaUnit.POINTS
        assert rate.series[-1].value == pytest.approx(83.56, abs=0.01)
        assert rate.series[0].value is None  # no PR opened that day: no rate, not 0%

    def test_merge_rate_without_opened_prs_is_none_not_zero(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        empty = count_tile(w, {}, DeltaUnit.PERCENT, "prs")
        rate = merge_rate_tile(empty, empty)
        assert rate.total is None and rate.delta is None and rate.reason is None


@pytest.mark.unit
class TestBuild:
    def test_empty_window(self) -> None:
        w = ShippedWindow.ending(TODAY, 14)
        m = build_shipped_metrics(w, [], {})
        assert (m.commits.total, m.commits.previous_total, m.commits.delta_display) == (0, 0, "0%")
        assert [p.value for p in m.commits.series] == [0] * 14
        assert m.repos_touched.total == 0 and m.repos == ()
        assert m.by_workflow == ()

    def test_empty_pr_tiles_are_zero_and_the_rate_is_none(self) -> None:
        m = build_shipped_metrics(ShippedWindow.ending(TODAY, 14), [], {})
        assert (m.prs_opened.total, m.prs_merged.total) == (0, 0)
        assert m.prs_opened.reason is None
        assert m.merge_rate.total is None and m.merge_rate.reason is None
        assert m.unavailable == ()

    def test_only_merges_of_prs_runs_created_count(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        summaries = {"e1": _summary("e1", "impl", ["acme/api"])}
        run_prs = [
            RunPullRequest("acme/api", 1, "e1", TODAY),
            RunPullRequest("acme/api", 1, "e1", TODAY),  # seen twice: one PR
            RunPullRequest("acme/web", 2, "e1", w.previous_start - timedelta(days=5)),
        ]
        merges = [
            MergedPullRequest("ACME/api", 1, TODAY),  # forge spelling differs in case
            MergedPullRequest("acme/api", 1, TODAY),  # delivered twice: one merge
            MergedPullRequest("acme/web", 2, w.start),  # opened before the windows: counted
            MergedPullRequest("owner/manual", 9, TODAY),  # no run created it
        ]
        m = build_shipped_metrics(w, [], summaries, run_prs=run_prs, merges=merges)
        assert (m.prs_opened.total, m.prs_opened.previous_total) == (1, 0)
        assert m.prs_merged.total == 2
        assert m.merge_rate.total == 200.0  # merged PRs opened earlier can exceed opened
        assert m.repos == ("acme/api", "acme/web")
        assert m.by_workflow[0].prs_opened == 1 and m.by_workflow[0].prs_merged == 2

    def test_a_sha_counts_once_on_its_first_day(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        rows = [
            CommitSighting("abc", "e1", TODAY),
            CommitSighting("abc", "e1", w.start),
            CommitSighting("def", "e1", TODAY),
        ]
        m = build_shipped_metrics(w, rows, {"e1": _summary("e1", "wf", ["a/x"])})
        assert m.commits.total == 2
        assert m.commits.series[0].value == 1 and m.commits.series[-1].value == 1

    def test_days_are_bucketed_as_given_and_outside_days_dropped(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        rows = [
            CommitSighting("in", "e1", TODAY),
            CommitSighting("prev", "e1", w.previous_start),
            CommitSighting("too-old", "e1", w.previous_start - timedelta(days=1)),
            CommitSighting("future", "e1", TODAY + timedelta(days=1)),
        ]
        m = build_shipped_metrics(w, rows, {"e1": _summary("e1", "wf", [])})
        assert (m.commits.total, m.commits.previous_total) == (1, 1)

    def test_repos_are_distinct_slugs_from_urls_and_slugs(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        summaries = {
            "e1": _summary("e1", "wf", ["https://github.com/acme/api.git", "acme/web"]),
            "e2": _summary("e2", "wf", ["https://github.com/acme/api", "not a repo"]),
        }
        rows = [CommitSighting("a", "e1", TODAY), CommitSighting("b", "e2", w.start)]
        m = build_shipped_metrics(w, rows, summaries)
        assert m.repos == ("acme/api", "acme/web")
        assert m.repos_touched.total == 2

    def test_workflow_filter_and_unattributed_commits(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        summaries = {
            "e1": _summary("e1", "impl", ["acme/api"]),
            "e2": _summary("e2", "docs", ["acme/docs"]),
        }
        rows = [
            CommitSighting("a", "e1", TODAY),
            CommitSighting("b", "e1", TODAY),
            CommitSighting("c", "e2", TODAY),
            CommitSighting("d", "ghost", TODAY),
        ]
        everything = build_shipped_metrics(w, rows, summaries)
        assert everything.commits.total == 4
        assert everything.commits_without_workflow == 1
        assert [
            (b.workflow_id, b.name, b.commits, b.repos_touched) for b in everything.by_workflow
        ] == [("impl", "IMPL", 2, 1), ("docs", "DOCS", 1, 1)]

        impl = build_shipped_metrics(w, rows, summaries, workflow_id="impl")
        assert impl.commits.total == 2 and impl.repos == ("acme/api",)
        assert impl.by_workflow == () and impl.workflow_id == "impl"


@pytest.mark.unit
class TestSeededScenario:
    """28 days shaped like the board's sample: 1,204 commits (+38%), 9 repos (+3)."""

    @staticmethod
    def _seed_prs() -> tuple[list[RunPullRequest], list[MergedPullRequest]]:
        """73 run PRs opened and 61 merged now; 59 and 48 in the window before."""
        w = ShippedWindow.ending(TODAY, 14)
        opened: list[RunPullRequest] = []
        merged: list[MergedPullRequest] = []
        for n in range(73 + 59):
            current = n < 73
            i = n % 14
            day = (w.start if current else w.previous_start) + timedelta(days=i)
            execution = f"exec-{'cur' if current else 'prev'}-{i}"
            repo = f"acme/repo-{i % 9 if current else i % 6}"
            opened.append(RunPullRequest(repo, n + 1, execution, day))
            if (current and n < 61) or (not current and n - 73 < 48):
                merged.append(MergedPullRequest(repo, n + 1, day))
        return opened, merged

    @staticmethod
    def _seed() -> tuple[list[CommitSighting], dict[str, WorkflowExecutionSummary]]:
        w = ShippedWindow.ending(TODAY, 14)
        workflows = ("sdlc-implement", "sdlc-review", "docs-sync")
        rows: list[CommitSighting] = []
        summaries: dict[str, WorkflowExecutionSummary] = {}
        for i in range(14):
            cur_day = w.start + timedelta(days=i)
            cur_exec = f"exec-cur-{i}"
            summaries[cur_exec] = _summary(
                cur_exec, workflows[i % 3], [f"https://github.com/acme/repo-{i % 9}"]
            )
            rows += [CommitSighting(f"c{i}-{n}", cur_exec, cur_day) for n in range(86)]

            prev_day = w.previous_start + timedelta(days=i)
            prev_exec = f"exec-prev-{i}"
            summaries[prev_exec] = _summary(prev_exec, workflows[i % 3], [f"acme/repo-{i % 6}"])
            rows += [
                CommitSighting(f"p{i}-{n}", prev_exec, prev_day) for n in range(63 if i < 4 else 62)
            ]
        return rows, summaries

    @pytest.mark.asyncio
    async def test_matches_the_board_shape(self) -> None:
        rows, summaries = self._seed()
        sightings = _Sightings(rows)
        executions = _Executions(summaries)
        opened, merged = self._seed_prs()
        prs = _PullRequests(opened, merged)
        service = ShippedMetricsQueryService(sightings, executions, prs, today=lambda: TODAY)

        m = await service.shipped(days=14)

        assert sightings.asked == (
            datetime(2026, 9, 12, tzinfo=UTC),
            datetime(2026, 10, 10, tzinfo=UTC),
        )
        assert prs.asked_merged == sightings.asked
        assert prs.asked_opened == (
            datetime(2026, 9, 12, tzinfo=UTC) - timedelta(days=MERGE_LOOKBACK_DAYS),
            datetime(2026, 10, 10, tzinfo=UTC),
        )
        assert len(executions.asked) == 28  # one keyed read, not one per execution
        assert (m.commits.total, m.commits.previous_total) == (1204, 872)
        assert (m.commits.total_display, m.commits.delta_display) == ("1,204", "+38%")
        assert len(m.commits.series) == 14 and {p.value for p in m.commits.series} == {86}
        assert (m.repos_touched.total, m.repos_touched.previous_total) == (9, 6)
        assert m.repos_touched.delta_display == "+3"
        assert m.repos == tuple(sorted(f"acme/repo-{i}" for i in range(9)))
        assert sum(b.commits for b in m.by_workflow) == 1204
        assert m.by_workflow[0].workflow_id == "sdlc-implement"  # 5 days x 86
        assert (m.prs_opened.total_display, m.prs_opened.delta_display) == ("73", "+24%")
        assert (m.prs_merged.total_display, m.prs_merged.delta_display) == ("61", "+27%")
        assert (m.merge_rate.total_display, m.merge_rate.delta_display) == ("84%", "+2 pts")
        assert m.merge_rate.total == pytest.approx(83.56, abs=0.01)  # percent, not a fraction
        assert sum(p.value for p in m.prs_opened.series) == 73

    def test_pr_tile_maths_on_the_board_numbers(self) -> None:
        """The board's sample (73 opened +24%, 61 merged +27%) implies 59 and 48
        before, which is a merge rate of 81% -> 84%: "+2 pts", not the "+5 pts"
        the mock shows. The mock's numbers are not mutually consistent.
        """
        w = ShippedWindow.ending(TODAY, 14)
        opened = count_tile(w, {TODAY: 73, w.previous_end: 59}, DeltaUnit.PERCENT, "prs")
        merged = count_tile(w, {TODAY: 61, w.previous_end: 48}, DeltaUnit.PERCENT, "prs")
        rate = merge_rate_tile(opened, merged)
        assert (opened.total_display, opened.delta_display) == ("73", "+24%")
        assert (merged.total_display, merged.delta_display) == ("61", "+27%")
        assert (rate.total_display, rate.delta_display) == ("84%", "+2 pts")


class _KeyedStore:
    """Only a keyed ``get``: ``by_ids`` must never scan or JSON-filter."""

    def __init__(self, rows: Mapping[str, ProjectionRecord]) -> None:
        self.rows = rows

    async def get(self, projection: str, key: str) -> ProjectionRecord | None:
        assert projection == "workflow_executions"
        return self.rows.get(key)


@pytest.mark.unit
class TestExecutionAttribution:
    @pytest.mark.asyncio
    async def test_by_ids_reads_only_the_ids_asked_for(self) -> None:
        from syn_domain.contexts.orchestration import ExecutionListReads

        store = _KeyedStore(
            {
                "e1": {"workflow_execution_id": "e1", "workflow_id": "wf", "repos": ["acme/api"]},
                "e2": {"workflow_execution_id": "e2", "workflow_id": "other"},
            }
        )
        found = await ExecutionListReads(cast("ProjectionStore", store)).by_ids(["e1", "missing"])
        assert list(found) == ["e1"]
        assert found["e1"].workflow_id == "wf" and found["e1"].repos == ("acme/api",)
