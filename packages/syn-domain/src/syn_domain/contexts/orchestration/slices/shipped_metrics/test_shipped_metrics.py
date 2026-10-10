"""Tests for the "Shipped by agents" read: window maths, deltas, tiles, cache."""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.slices.shipped_metrics import (
    DeltaUnit,
    ShippedDayRow,
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
)

if TYPE_CHECKING:
    from collections.abc import Sequence

TODAY = date(2026, 10, 9)


def _row(day: date, repo: str = "acme/api", wf: str = "impl", **counts: int) -> ShippedDayRow:
    return ShippedDayRow(
        day=day, repository=repo, workflow_id=wf, workflow_name=wf.upper(), **counts
    )


class _Ledger:
    """Serves fixed rollup rows and counts the reads."""

    def __init__(self, rows: Sequence[ShippedDayRow], delay: float = 0.0) -> None:
        self.rows = list(rows)
        self.reads: list[tuple[date, date, str | None]] = []
        self.delay = delay
        self.fail = False

    async def daily(
        self, start: date, end: date, workflow_id: str | None = None
    ) -> Sequence[ShippedDayRow]:
        self.reads.append((start, end, workflow_id))
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("store down")
        return [
            r
            for r in self.rows
            if start <= r.day <= end and (workflow_id is None or r.workflow_id == workflow_id)
        ]

    async def record_commit(self, *_: object) -> None: ...
    async def record_pull_request_opened(self, *_: object) -> None: ...
    async def record_pull_request_merged(self, *_: object) -> None: ...


@pytest.mark.unit
class TestWindow:
    def test_fourteen_days_end_today_inclusive(self) -> None:
        w = ShippedWindow.ending(TODAY, 14)
        assert (w.start, w.end) == (date(2026, 9, 26), TODAY)
        assert (w.previous_start, w.previous_end) == (date(2026, 9, 12), date(2026, 9, 25))
        assert w.current_days()[0] == w.start and w.current_days()[-1] == TODAY

    @pytest.mark.parametrize("days", [7, 14, 30])
    def test_windows_are_adjacent_and_equal_length(self, days: int) -> None:
        w = ShippedWindow.ending(TODAY, days)
        assert w.previous_end + timedelta(days=1) == w.start
        assert (w.previous_end - w.previous_start).days + 1 == days
        assert (w.end - w.start).days + 1 == days

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

    @pytest.mark.parametrize(("total", "previous"), [(5, 0), (0, 0)])
    def test_percent_is_none_whenever_the_previous_window_is_zero(
        self, total: int, previous: int
    ) -> None:
        assert format_percent_delta(total, previous)[0] is None

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
        tile = count_tile(w, {TODAY: 3, w.start: 2, w.previous_end: 4}, DeltaUnit.PERCENT, "t")
        assert (tile.total, tile.previous_total, tile.delta, tile.delta_display) == (
            5,
            4,
            1,
            "+25%",
        )
        assert [p.value for p in tile.series] == [2, 0, 0, 0, 0, 0, 3]

    def test_distinct_tile_counts_the_union_not_the_sum(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        per_day = {w.start: {"a/x", "a/y"}, TODAY: {"a/x", "a/z"}, w.previous_end: {"a/x"}}
        tile = distinct_tile(w, per_day, DeltaUnit.COUNT, "t")
        assert (tile.total, tile.previous_total, tile.delta_display) == (3, 1, "+2")


@pytest.mark.unit
class TestMergeRateIsACohortConversion:
    def test_of_prs_opened_in_the_window_the_share_merged_by_now(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        rows = [
            _row(TODAY, prs_opened=4, prs_opened_merged=3),
            _row(w.previous_end, prs_opened=5, prs_opened_merged=4),
            # Older PRs merged in this window count as merges, not as the cohort.
            _row(w.start, prs_merged=10),
        ]
        m = build_shipped_metrics(w, rows)
        assert m.merge_rate.total == 75.0
        assert m.merge_rate.previous_total == 80.0
        assert m.merge_rate.delta_display == "-5 pts"
        assert m.prs_merged.total == 10  # throughput tile, separate from the rate
        assert m.merge_rate.series[-1].value == 75.0
        assert m.merge_rate.series[0].value is None  # nothing opened that day

    def test_never_exceeds_one_hundred_for_any_rollup(self) -> None:
        w = ShippedWindow.ending(TODAY, 14)
        rng = random.Random(1857)
        for _ in range(200):
            rows = []
            for i in range(28):
                opened = rng.randint(0, 6)
                rows.append(
                    _row(
                        w.previous_start + timedelta(days=i),
                        prs_opened=opened,
                        prs_opened_merged=rng.randint(0, opened),
                        prs_merged=rng.randint(0, 20),
                    )
                )
            rate = build_shipped_metrics(w, rows).merge_rate
            for value in (rate.total, rate.previous_total, *(p.value for p in rate.series)):
                assert value is None or 0.0 <= value <= 100.0

    def test_no_pr_opened_is_none_not_zero(self) -> None:
        m = build_shipped_metrics(ShippedWindow.ending(TODAY, 7), [])
        assert m.merge_rate.total is None and m.merge_rate.delta is None


@pytest.mark.unit
class TestBuild:
    def test_empty_window(self) -> None:
        m = build_shipped_metrics(ShippedWindow.ending(TODAY, 14), [])
        assert (m.commits.total, m.commits.previous_total, m.commits.delta_display) == (0, 0, "0%")
        assert [p.value for p in m.commits.series] == [0] * 14
        assert m.repos == () and m.by_workflow == () and m.unavailable == ()

    def test_rows_outside_both_windows_are_ignored(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        rows = [_row(w.previous_start - timedelta(days=1), commits=9), _row(TODAY, commits=1)]
        assert build_shipped_metrics(w, rows).commits.total == 1

    def test_repos_are_distinct_and_only_where_something_shipped(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        rows = [
            _row(TODAY, "acme/api", commits=1),
            _row(w.start, "acme/api", "docs", prs_opened=1),
            _row(w.start, "acme/web", prs_opened_merged=1),  # a counter that is not activity
        ]
        m = build_shipped_metrics(w, rows)
        assert m.repos == ("acme/api",) and m.repos_touched.total == 1

    def test_by_workflow_and_the_filter(self) -> None:
        w = ShippedWindow.ending(TODAY, 7)
        rows = [
            _row(TODAY, "acme/api", "impl", commits=5, prs_opened=2, prs_merged=1),
            _row(TODAY, "acme/web", "impl", commits=1),
            _row(TODAY, "acme/docs", "docs", commits=2, prs_merged=3),
            _row(w.previous_end, "acme/x", "old", commits=50),  # previous window only
        ]
        m = build_shipped_metrics(w, rows)
        assert [
            (b.workflow_id, b.name, b.commits, b.prs_merged, b.repos_touched) for b in m.by_workflow
        ] == [
            ("impl", "IMPL", 6, 1, 2),
            ("docs", "DOCS", 2, 3, 1),
        ]
        assert build_shipped_metrics(w, rows, workflow_id="impl").by_workflow == ()


@pytest.mark.unit
class TestSeededScenario:
    """28 days shaped like the board: 1,204 commits (+38%), 73 PRs (+24%), 9 repos (+3)."""

    @staticmethod
    def _rows() -> list[ShippedDayRow]:
        w = ShippedWindow.ending(TODAY, 14)
        workflows = ("sdlc-implement", "sdlc-review", "docs-sync")
        rows: list[ShippedDayRow] = []
        for i in range(14):
            cur, prev = w.start + timedelta(days=i), w.previous_start + timedelta(days=i)
            opened_now = 6 if i < 3 else 5  # 73
            opened_then = 5 if i < 3 else 4  # 59
            rows.append(
                _row(
                    cur,
                    f"acme/repo-{i % 9}",
                    workflows[i % 3],
                    commits=86,
                    prs_opened=opened_now,
                    prs_opened_merged=opened_now - (1 if i < 12 else 0),  # 61 of 73
                    prs_merged=5 if i < 5 else 4,  # 61
                )
            )
            rows.append(
                _row(
                    prev,
                    f"acme/repo-{i % 6}",
                    workflows[i % 3],
                    commits=63 if i < 4 else 62,
                    prs_opened=opened_then,
                    prs_opened_merged=opened_then - (1 if i < 11 else 0),  # 48 of 59
                    prs_merged=4 if i < 6 else 3,  # 48
                )
            )
        return rows

    @pytest.mark.asyncio
    async def test_matches_the_board_shape_from_one_rollup_read(self) -> None:
        ledger = _Ledger(self._rows())
        m = await ShippedMetricsQueryService(ledger, today=lambda: TODAY).shipped(days=14)
        assert ledger.reads == [(date(2026, 9, 12), TODAY, None)]
        assert (m.commits.total_display, m.commits.delta_display) == ("1,204", "+38%")
        assert (m.prs_opened.total_display, m.prs_opened.delta_display) == ("73", "+24%")
        assert (m.prs_merged.total_display, m.prs_merged.delta_display) == ("61", "+27%")
        assert (m.merge_rate.total_display, m.merge_rate.delta_display) == ("84%", "+2 pts")
        assert (m.repos_touched.total, m.repos_touched.delta_display) == (9, "+3")
        assert sum(b.commits for b in m.by_workflow) == 1204


@pytest.mark.unit
class TestCacheAndCoalescing:
    @pytest.mark.asyncio
    async def test_concurrent_requests_share_one_read(self) -> None:
        ledger = _Ledger([_row(TODAY, commits=1)], delay=0.01)
        service = ShippedMetricsQueryService(ledger, today=lambda: TODAY)
        results = await asyncio.gather(*(service.shipped(days=14) for _ in range(20)))
        assert len(ledger.reads) == 1
        assert all(r is results[0] for r in results)

    @pytest.mark.asyncio
    async def test_keys_are_days_and_workflow_and_expire(self) -> None:
        now = [0.0]
        ledger = _Ledger([_row(TODAY, commits=1)])
        service = ShippedMetricsQueryService(
            ledger, today=lambda: TODAY, clock=lambda: now[0], cache_seconds=30
        )
        await service.shipped(days=14)
        await service.shipped(days=14)
        await service.shipped(days=7)
        await service.shipped(days=14, workflow_id="impl")
        assert len(ledger.reads) == 3
        now[0] = 31.0
        await service.shipped(days=14)
        assert len(ledger.reads) == 4

    @pytest.mark.asyncio
    async def test_a_new_utc_day_is_a_new_key(self) -> None:
        today = [TODAY]
        ledger = _Ledger([])
        service = ShippedMetricsQueryService(ledger, today=lambda: today[0], clock=lambda: 0.0)
        await service.shipped()
        today[0] = TODAY + timedelta(days=1)
        await service.shipped()
        assert [r[1] for r in ledger.reads] == [TODAY, TODAY + timedelta(days=1)]

    @pytest.mark.asyncio
    async def test_a_failed_read_is_not_cached_and_reaches_every_waiter(self) -> None:
        ledger = _Ledger([], delay=0.01)
        ledger.fail = True
        service = ShippedMetricsQueryService(ledger, today=lambda: TODAY)
        outcomes = await asyncio.gather(
            *(service.shipped() for _ in range(3)), return_exceptions=True
        )
        assert all(isinstance(o, RuntimeError) for o in outcomes)
        ledger.fail = False
        await service.shipped()
        assert len(ledger.reads) == 2


@pytest.mark.unit
def test_now_is_utc() -> None:
    # The service's default "today" is the UTC date, whatever the host zone.
    from syn_domain.contexts.orchestration.slices.shipped_metrics.query_service import utc_today

    assert utc_today() == datetime.now(UTC).date()
