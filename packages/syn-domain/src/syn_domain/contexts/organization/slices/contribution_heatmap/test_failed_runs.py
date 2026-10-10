"""The heatmap's per-day ``failed``: executions that ENDED failed that UTC day."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from syn_domain.contexts.organization.slices.conftest import FakeProjectionStore
from syn_domain.contexts.organization.slices.contribution_heatmap.failed_runs import (
    EndedRun,
    failed_runs_by_day,
    failures_by_day,
)

START = date(2026, 10, 1)
END = date(2026, 10, 7)


@pytest.mark.unit
class TestFailuresByDay:
    def test_counts_on_the_utc_day_the_run_ended(self) -> None:
        runs = [
            EndedRun("a", datetime(2026, 10, 2, 23, 30, tzinfo=UTC)),
            EndedRun("b", datetime.fromisoformat("2026-10-02T20:00:00-05:00")),  # 10-03 UTC
            EndedRun("c", None),
            EndedRun("d", datetime(2026, 9, 30, 23, 59, tzinfo=UTC)),  # before the window
        ]
        assert failures_by_day(runs, START, END, None) == {
            date(2026, 10, 2): 1,
            date(2026, 10, 3): 1,
        }

    def test_execution_filter(self) -> None:
        runs = [EndedRun("a", datetime(2026, 10, 2, tzinfo=UTC))]
        assert failures_by_day(runs, START, END, {"other"}) == {}


@pytest.mark.unit
class TestFailedRunsByDay:
    @pytest.mark.asyncio
    async def test_reads_only_failed_runs_from_the_execution_list(self) -> None:
        store = FakeProjectionStore()
        rows = {
            "f1": ("failed", "2026-10-02T01:00:00Z", "2026-10-03T02:00:00Z"),
            "f2": ("failed", "2026-09-28T01:00:00Z", "2026-10-01T00:30:00Z"),  # started before
            "f3": ("failed", "2026-08-01T01:00:00Z", "2026-10-01T00:30:00Z"),  # beyond run span
            "ok": ("completed", "2026-10-02T01:00:00Z", "2026-10-02T03:00:00Z"),
            "cx": ("cancelled", "2026-10-02T01:00:00Z", "2026-10-02T03:00:00Z"),
        }
        for execution_id, (status, started, completed) in rows.items():
            await store.save(
                "workflow_executions",
                execution_id,
                {
                    "workflow_execution_id": execution_id,
                    "workflow_id": "wf",
                    "status": status,
                    "started_at": started,
                    "completed_at": completed,
                },
            )
        assert await failed_runs_by_day(store, START, END, None) == {
            date(2026, 10, 3): 1,
            date(2026, 10, 1): 1,
        }
