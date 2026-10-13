"""Executions that ended failed, per UTC day, for the contribution heatmap.

A day's ``failed`` is the number of executions whose ``status`` is ``failed``
and whose ``completed_at`` (the ``failed_at`` of WorkflowFailed) falls on that
UTC day: the day the run ended, not the day it started. Read from the
``workflow_executions`` read model (orchestration's ``list_executions``
slice), never an aggregate, so it is as replay-safe as that projection and
needs no projection of its own.

Selected and bucketed by ``completed_at`` alone, in the store: one page
query over failed executions that ENDED in the window, whenever they started.
A failure recorded without a start (the orphaned-failure row the projection
writes when it never saw the start, #598) counts like any other.
Cancelled and interrupted runs are not failures.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING

from syn_domain.contexts.organization._shared.projection_names import WORKFLOW_EXECUTIONS
from syn_domain.pagination import coerce_datetime
from syn_domain.projection_page import PageQuery, StatusOf, page_projection

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

    from event_sourcing import ProjectionStore

    from syn_domain.pagination import ProjectionRecord

FAILED = "failed"


@dataclass(frozen=True)
class EndedRun:
    """An execution and the instant it ended."""

    execution_id: str
    ended_at: datetime | None


def _ended_run(record: ProjectionRecord) -> EndedRun:
    return EndedRun(
        execution_id=str(record.get("workflow_execution_id") or record.get("execution_id") or ""),
        ended_at=coerce_datetime(record.get("completed_at")),
    )


def failures_by_day(
    runs: Iterable[EndedRun], start: date, end: date, execution_ids: Collection[str] | None
) -> dict[date, int]:
    """Count ``runs`` per UTC day of ``ended_at`` within ``[start, end]``."""
    counts: dict[date, int] = defaultdict(int)
    for run in runs:
        if run.ended_at is None:
            continue
        if execution_ids is not None and run.execution_id not in execution_ids:
            continue
        day = run.ended_at.astimezone(UTC).date()
        if start <= day <= end:
            counts[day] += 1
    return dict(counts)


async def failed_runs_by_day(
    store: ProjectionStore, start: date, end: date, execution_ids: Collection[str] | None
) -> dict[date, int]:
    """Executions that ended failed on each UTC day of ``[start, end]``."""
    query = PageQuery(
        status=StatusOf.text("status"),
        timestamp_field="completed_at",
        statuses=frozenset({FAILED}),
        after=datetime.combine(start, time.min, tzinfo=UTC),
        before=datetime.combine(end, time.max, tzinfo=UTC),
        key_field="workflow_execution_id",
    )
    page = await page_projection(store, WORKFLOW_EXECUTIONS, query, to_row=_ended_run)
    return failures_by_day(page.rows, start, end, execution_ids)
