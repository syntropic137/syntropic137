"""Trend rows: one point per run, for the eval and workflow charts (#1788).

Built from the same reads the runs views use, so a trend point and its run row
cannot disagree: an eval's points are ``eval_run_facts`` (``GET /evals/{id}/runs``),
a workflow's are the execution list filtered by workflow plus the same
batched ``RunReads`` (each source read once per page, never per row; the
rules ``GET /executions/{id}`` applies). Newest first, paged like every list endpoint, so
page 1 is the latest runs; a chart reverses it.

Change markers come from the definition's own stream, never from the runs:
an eval's goal or baseline edits (``EvalRecord.definition_changes``), a
workflow's create, reinstall and phase edits (``WorkflowDefinitionHistory``).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_api.routes.eval_runs import RunReads, duration_display, eval_run_facts
from syn_api.routes.executions.queries import phase_duration
from syn_api.types import (
    DefinitionChangeResponse,
    DurationTrendSummaryResponse,
    EvalTrendPointResponse,
    EvalTrendResponse,
    PhaseDurationResponse,
    TrendDefinition,
    WorkflowCardTrendResponse,
    WorkflowTrendPointResponse,
    WorkflowTrendResponse,
)
from syn_domain.contexts.orchestration import DefinitionChangeKind, ExecutionListReads
from syn_domain.contexts.orchestration.domain.read_models.workflow_definition_changes import (
    version_at,
)
from syn_shared.display.formatters import format_cost

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_adapters.projections.manager import ProjectionManager
    from syn_domain.contexts.orchestration.domain.read_models.eval_runs import EvalRunFacts
    from syn_domain.contexts.orchestration.domain.read_models.eval_summary import EvalRecord
    from syn_domain.contexts.orchestration.domain.read_models.workflow_definition_changes import (
        WorkflowDefinitionHistory,
    )
    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
        WorkflowExecutionSummary,
    )
    from syn_domain.pagination import Page


def utc_iso(value: datetime | str | None) -> str | None:
    """ISO 8601 in UTC. A naive time is taken as UTC; an unparseable one is null."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def score_percent(fraction: float | None) -> int | None:
    """A recorded score in [0, 1] as an integer 0 to 100."""
    return None if fraction is None else round(fraction * 100)


def _definition(changes: Sequence[DefinitionChangeResponse]) -> TrendDefinition:
    last = changes[-1] if changes else None
    return TrendDefinition(
        definition_version=None if last is None else last.definition_version,
        definition_changed_at=None if last is None else last.changed_at,
        definition_changes=list(changes),
    )


def eval_changes(record: EvalRecord) -> list[DefinitionChangeResponse]:
    return [
        DefinitionChangeResponse(
            definition_version=str(change.definition_version),
            changed_at=utc_iso(change.changed_at) or change.changed_at,
            kind=DefinitionChangeKind.CREATED
            if change.definition_version == 1
            else DefinitionChangeKind.UPDATED,
        )
        for change in record.definition_changes
    ]


def workflow_changes(history: WorkflowDefinitionHistory) -> list[DefinitionChangeResponse]:
    return [
        DefinitionChangeResponse(
            definition_version=change.definition_version,
            changed_at=utc_iso(change.changed_at) or change.changed_at,
            kind=change.kind,
        )
        for change in history.changes
    ]


def _version_at(changes: Sequence[DefinitionChangeResponse], date: str | None) -> str | None:
    """The definition version current at ``date`` (``version_at``: latest in stream at or before)."""
    if date is None:
        return None
    return version_at(
        ((datetime.fromisoformat(c.changed_at), c.definition_version) for c in changes),
        datetime.fromisoformat(date),
    )


def _eval_point(
    run: EvalRunFacts, changes: Sequence[DefinitionChangeResponse]
) -> EvalTrendPointResponse:
    score = run.score
    date = utc_iso(run.started_at)
    return EvalTrendPointResponse(
        execution_id=run.execution_id,
        date=date,
        workflow_id=run.workflow_id,
        workflow_version=run.workflow_version,
        eval_definition_version=_version_at(changes, date),
        verifier_model=run.final_phase_model,
        observed_models=list(run.variant_models),
        judge_model=None if score is None else score.judge_model,
        score=None if score is None else score_percent(score.score),
        verdict=None if score is None else score.verdict,
        cost_usd=run.total_cost_usd,
        cost_is_lower_bound=run.unpriced_observation_count > 0,
        cost_display=format_cost(run.total_cost_usd, run.unpriced_observation_count),
        duration_seconds=run.duration_seconds,
        duration_is_lower_bound=run.unknown_duration_phase_count > 0,
        duration_display=duration_display(run.duration_seconds, run.unknown_duration_phase_count),
        tokens=run.total_tokens,
    )


async def eval_trend(
    manager: ProjectionManager, record: EvalRecord, *, page: int, page_size: int
) -> EvalTrendResponse:
    """One page of the eval's current runs as trend points, with its change markers."""
    runs, total = await eval_run_facts(
        manager, record.eval_id, offset=(page - 1) * page_size, limit=page_size
    )
    changes = eval_changes(record)
    return EvalTrendResponse(
        **_definition(changes).model_dump(),
        eval_id=record.eval_id,
        items=[_eval_point(run, changes) for run in runs],
        total=total,
        page=page,
        page_size=page_size,
    )


def _workflow_point(reads: RunReads, row: WorkflowExecutionSummary) -> WorkflowTrendPointResponse:
    facts = reads.facts(row, None)
    detail = reads.details.get(row.workflow_execution_id)
    cost, unpriced = facts.total_cost_usd, facts.unpriced_observation_count
    duration, unknown = facts.duration_seconds, facts.unknown_duration_phase_count
    return WorkflowTrendPointResponse(
        execution_id=row.workflow_execution_id,
        date=utc_iso(row.started_at),
        status=row.status,
        workflow_version=row.workflow_version,
        cost_usd=cost,
        cost_is_lower_bound=unpriced > 0,
        cost_display=format_cost(cost, unpriced),
        duration_seconds=duration,
        duration_is_lower_bound=unknown > 0,
        duration_display=duration_display(duration, unknown),
        tokens=row.total_tokens,
        phase_durations=[]
        if detail is None
        else [
            PhaseDurationResponse(
                phase_id=p.workflow_phase_id,
                phase_name=p.name,
                duration_seconds=phase_duration(p),
            )
            for p in detail.phases
        ],
    )


async def workflow_trend(
    manager: ProjectionManager, workflow_id: str, *, page: int, page_size: int
) -> WorkflowTrendResponse:
    """One page of the workflow's executions as trend points, with its change markers."""
    rows = await ExecutionListReads(manager.store).page(
        workflow_id=workflow_id, offset=(page - 1) * page_size, limit=page_size
    )
    reads = await RunReads.load(manager, [row.workflow_execution_id for row in rows.rows])
    return await _workflow_trend(manager, reads, workflow_id, rows, page=page, page_size=page_size)


async def workflow_trends(
    manager: ProjectionManager, workflow_ids: Sequence[str], *, page_size: int
) -> list[WorkflowCardTrendResponse]:
    """Each workflow's latest ``page_size`` runs as trend points, in the order given (#1872).

    Ids that name no workflow are left out. The cost and duration reads for
    every run of every workflow are one batched ``RunReads``, so the Lane 2
    round trips do not grow with the number of ids.
    """
    executions = ExecutionListReads(manager.store)
    pages = [
        (workflow_id, await executions.page(workflow_id=workflow_id, offset=0, limit=page_size))
        for workflow_id in workflow_ids
        if await manager.workflow_detail.get_by_id(workflow_id) is not None
    ]
    reads = await RunReads.load(
        manager, [row.workflow_execution_id for _, rows in pages for row in rows.rows]
    )
    trends = [
        await _workflow_trend(manager, reads, workflow_id, rows, page=1, page_size=page_size)
        for workflow_id, rows in pages
    ]
    return [
        WorkflowCardTrendResponse(
            **trend.model_dump(), duration_trend=duration_trend(trend.items, trend.total)
        )
        for trend in trends
    ]


TREND_WINDOW = 12
"""Measured runs a card's duration trend looks back over."""
TREND_MIN_RUNS = 3
"""Fewer measured runs than this read "Too few runs"."""
STEADY_PCT = 5
"""A fitted change smaller than this, in percent, reads "Steady"."""
_TREND_WORD = {"faster": "Faster", "slower": "Slower", "steady": "Steady"}
_TREND_SIGN = {"faster": "\u2212", "slower": "+", "steady": "\u00b1"}


def recent_durations(points: Sequence[WorkflowTrendPointResponse]) -> list[float]:
    """Measured durations of dated runs, oldest first, the last ``TREND_WINDOW`` of them.

    A lower-bound duration is a floor, not a measurement, so it is left out.
    """
    measured = [
        (p.date, p.duration_seconds)
        for p in points
        if p.date and not p.duration_is_lower_bound and p.duration_seconds is not None
    ]
    measured.sort(key=lambda pair: pair[0])
    return [d for _, d in measured[-TREND_WINDOW:]]


def duration_change_pct(durations: Sequence[float]) -> int:
    """Least-squares fitted change from the first run to the last, percent (negative is faster)."""
    n = len(durations)
    if n < 2:
        return 0
    mean = sum(durations) / n
    mx = (n - 1) / 2
    sxx = sum((x - mx) ** 2 for x in range(n))
    slope = sum((x - mx) * (y - mean) for x, y in enumerate(durations)) / sxx
    start, end = mean - slope * mx, mean + slope * mx
    if start <= 0:
        return 0
    return math.floor((end - start) / start * 100 + 0.5)


def duration_trend(
    points: Sequence[WorkflowTrendPointResponse], runs_count: int
) -> DurationTrendSummaryResponse:
    """The card's Faster / Slower / Steady label for a workflow's latest trend points.

    ``runs_count`` is every run of the workflow: when it has runs, the empty
    state never reads "No runs yet".
    """
    ds = recent_durations(points)
    if not ds:
        return _empty_trend(has_points=bool(points), has_runs=runs_count > 0)
    if len(ds) < TREND_MIN_RUNS:
        return _few_trend(len(ds))
    return _classified_trend(duration_change_pct(ds), len(ds))


def _empty_trend(*, has_points: bool, has_runs: bool) -> DurationTrendSummaryResponse:
    """No measured duration: says why, and never "No runs yet" when the workflow has runs."""
    if has_points:
        word, label = ("No finished runs" if has_runs else "No runs yet"), "No finished runs yet"
    elif has_runs:
        word, label = "No trend", "Duration trend not available"
    else:
        word, label = "No runs yet", "No runs yet"
    return DurationTrendSummaryResponse(
        kind="none", pct=0, runs=0, word_display=word, sub_display="\u2014", label_display=label
    )


def _few_trend(n: int) -> DurationTrendSummaryResponse:
    runs = f"{n} {'run' if n == 1 else 'runs'}"
    return DurationTrendSummaryResponse(
        kind="few",
        pct=0,
        runs=n,
        word_display="Too few runs",
        sub_display=runs,
        label_display=f"Duration trend: too few runs to tell ({runs})",
    )


def _classified_trend(pct: int, n: int) -> DurationTrendSummaryResponse:
    size = abs(pct)
    kind = "steady" if size < STEADY_PCT else "faster" if pct < 0 else "slower"
    how = "steady" if kind == "steady" else f"{size}% {kind}"
    return DurationTrendSummaryResponse(
        kind=kind,
        pct=pct,
        runs=n,
        word_display=_TREND_WORD[kind],
        sub_display=f"{_TREND_SIGN[kind]}{size}% time, last {n}",
        label_display=f"Duration trend: {how} over the last {n} runs",
    )


async def _workflow_trend(
    manager: ProjectionManager,
    reads: RunReads,
    workflow_id: str,
    rows: Page[WorkflowExecutionSummary],
    *,
    page: int,
    page_size: int,
) -> WorkflowTrendResponse:
    changes = workflow_changes(await manager.workflow_detail.definition_history(workflow_id))
    return WorkflowTrendResponse(
        **_definition(changes).model_dump(),
        workflow_id=workflow_id,
        items=[_workflow_point(reads, row) for row in rows.rows],
        total=rows.total,
        page=page,
        page_size=page_size,
    )
