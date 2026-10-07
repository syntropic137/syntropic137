"""Read the scorecard's inputs and render its response.

Reads are bounded by the window: the day index names the runs that ended in it
(plus those still running), their resume chains are completed from the same
projection, and Lane-2 cost and tool-call tallies are read for exactly those
ids. Nothing here decides a number; ``compute_scorecard`` does.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from syn_api.scorecard_types import (
    ScorecardDailyPointResponse,
    ScorecardDeliveryResponse,
    ScorecardOutcomeCountsResponse,
    ScorecardOutcomeRowResponse,
    ScorecardPhaseTypeResponse,
    ScorecardResponse,
    ScorecardTargetResponse,
    ScorecardThroughputResponse,
)
from syn_domain.contexts.orchestration import (
    ScorecardProjection,
    compute_scorecard,
)
from syn_domain.contexts.orchestration import scorecard_day_key as day_key
from syn_shared.display.formatters import (
    EM_DASH,
    format_cost,
    format_duration_seconds,
    format_tokens,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping
    from decimal import Decimal

    from event_sourcing import ProjectionStore

    from syn_domain.contexts.orchestration import (
        ExecutionSpend,
        OutcomeCounts,
        OutcomeRow,
        PhaseTypeStats,
        Scorecard,
        ScorecardRun,
        TargetResult,
    )

MAX_WINDOW_DAYS = 30
_WINDOW = re.compile(r"^(\d{1,2})d$")


class WindowError(ValueError):
    """The window is not ``<N>d`` with 1 <= N <= 30."""


def parse_window(window: str) -> int:
    match = _WINDOW.match(window)
    days = int(match.group(1)) if match else 0
    if not 1 <= days <= MAX_WINDOW_DAYS:
        raise WindowError(f"window must be 1d..{MAX_WINDOW_DAYS}d, got {window!r}")
    return days


async def load_runs(
    projection: ScorecardProjection, now: datetime, window_days: int
) -> dict[str, ScorecardRun]:
    """The window's runs and every member of their resume chains, by execution id."""
    today = now.astimezone(UTC)
    days = [day_key(today - timedelta(days=i)) for i in range(window_days)]
    runs = {run.execution_id: run for run in await projection.runs_for_days(days)}
    for run in list(runs.values()):
        for member_id in run.chain:
            if member_id not in runs and (member := await projection.get_run(member_id)):
                runs[member_id] = member
    return runs


async def build_scorecard(
    *,
    store: ProjectionStore,
    read_costs: Callable[[Iterable[str]], Awaitable[Mapping[str, ExecutionSpend]]],
    read_tool_calls: Callable[[Iterable[str]], Awaitable[Mapping[str, int]]],
    read_session_models: Callable[[Iterable[str]], Awaitable[Mapping[str, Mapping[str, Decimal]]]],
    window: str,
    now: datetime | None = None,
) -> ScorecardResponse:
    window_days = parse_window(window)
    moment = now or datetime.now(UTC)
    runs = await load_runs(ScorecardProjection(store), moment, window_days)
    sessions = [p.session_id for r in runs.values() for p in r.phases if p.session_id]
    card = compute_scorecard(
        runs=runs,
        spend_by_execution=await read_costs(list(runs)),
        tool_calls_by_session=await read_tool_calls(sessions),
        cost_by_session_model=await read_session_models(sessions),
        now=moment,
        window_days=window_days,
    )
    return render(card, window)


def _rate(value: float | None) -> str:
    return EM_DASH if value is None else f"{value:.0%}"


def _tokens(value: float | None) -> str:
    return format_tokens(None if value is None else round(value))


def _number(value: float | None) -> str:
    return EM_DASH if value is None else f"{value:,.1f}"


def _counts(counts: OutcomeCounts) -> ScorecardOutcomeCountsResponse:
    return ScorecardOutcomeCountsResponse(
        total=counts.total,
        completed=counts.completed,
        failed_platform=counts.failed_platform,
        failed_task=counts.failed_task,
        failed_correct_refusal=counts.failed_correct_refusal,
        failed_unclassified=counts.failed_unclassified,
        cancelled=counts.cancelled,
        completed_platform_failure_free=counts.completed_platform_failure_free,
        platform_failure_free_rate=counts.platform_failure_free_rate,
        platform_failure_free_rate_display=_rate(counts.platform_failure_free_rate),
    )


_TARGET_DISPLAY: dict[str, Callable[[float | None], str]] = {
    "Platform-failure-free completion": _rate,
    "Median verify tokens": _tokens,
    "Cost per merged PR (USD)": lambda v: format_cost(v),
    "Stable concurrency": _number,
}


def _usd(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _phase(p: PhaseTypeStats) -> ScorecardPhaseTypeResponse:
    return ScorecardPhaseTypeResponse(
        phase_type=p.phase_type.value,
        phase_count=p.phase_count,
        median_tokens=p.median_tokens,
        median_tokens_display=_tokens(p.median_tokens),
        p90_tokens=p.p90_tokens,
        p90_tokens_display=_tokens(p.p90_tokens),
        cache_read_share=p.cache_read_share,
        cache_read_share_display=_rate(p.cache_read_share),
        median_tool_calls=p.median_tool_calls,
        median_tool_calls_display=_number(p.median_tool_calls),
        tokens_per_tool_call=p.tokens_per_tool_call,
        tokens_per_tool_call_display=_tokens(p.tokens_per_tool_call),
        phases_with_tool_counts=p.phases_with_tool_counts,
        median_cost_usd=_usd(p.median_cost_usd),
        median_cost_display=format_cost(p.median_cost_usd),
        p90_cost_usd=_usd(p.p90_cost_usd),
        p90_cost_display=format_cost(p.p90_cost_usd),
        phases_with_cost=p.phases_with_cost,
    )


def _row(row: OutcomeRow) -> ScorecardOutcomeRowResponse:
    return ScorecardOutcomeRowResponse(
        key=row.key, counts=_counts(row.counts), phases=[_phase(p) for p in row.phases]
    )


def _target(target: TargetResult) -> ScorecardTargetResponse:
    display = _TARGET_DISPLAY.get(target.name, _number)
    return ScorecardTargetResponse(
        name=target.name,
        actual=target.actual,
        actual_display=display(target.actual),
        target=target.target,
        target_display=("≥ " if target.higher_is_better else "≤ ") + display(target.target),
        higher_is_better=target.higher_is_better,
        status=target.status.value,
    )


def render(card: Scorecard, window: str) -> ScorecardResponse:
    days = f"the {card.window_days} UTC day{'s' if card.window_days > 1 else ''} to now"
    throughput = card.throughput
    return ScorecardResponse(
        window=window,
        window_start=card.window_start.isoformat(),
        window_end=card.window_end.isoformat(),
        scope=(
            f"Resume chains whose final run ended in {days}. A resumed run counts once, "
            "as its chain's final outcome; runs still in flight are not counted. "
            "Rate = completed chains with no platform failure anywhere in the chain, "
            "over finished chains other than cancelled ones."
        ),
        counts=_counts(card.counts),
        by_workflow=[_row(r) for r in card.by_workflow],
        by_model=[_row(r) for r in card.by_model],
        phases=[_phase(p) for p in card.phases],
        phases_scope=(
            "Completed and failed phases of every run in those chains, resumed runs included, "
            "grouped by phase_id (fix_2 is a fix; finalize_pr and open_pr are finalize; "
            "quickfix is implement; anything else is other). Tool calls come from each "
            "phase's session tally; phases_with_tool_counts says how many had one. Cost is the "
            "Lane-2 cost its execution recorded for that phase_id, failed phases included; "
            "median and p90 cost are over the phases_with_cost phases that had one. "
            "by_model keys are the models each phase's session REPORTED in its Lane-2 "
            "usage, never the configured agent or an alias; a phase with no observed model "
            "is in no model row. A model row counts a chain's outcome if any of its phases "
            "observed that model, and only those phases (and that model's share of their "
            "cost) in its phase statistics."
        ),
        daily=[
            ScorecardDailyPointResponse(
                day=d.day,
                counts=_counts(d.counts),
                cost_usd=str(d.cost_usd),
                cost_display=format_cost(d.cost_usd),
                median_verify_tokens=d.median_verify_tokens,
                median_verify_tokens_display=_tokens(d.median_verify_tokens),
                median_verify_cost_usd=_usd(d.median_verify_cost_usd),
                median_verify_cost_display=format_cost(d.median_verify_cost_usd),
                peak_concurrency=d.peak_concurrency,
            )
            for d in card.daily
        ],
        throughput=ScorecardThroughputResponse(
            average_concurrency=throughput.average_concurrency,
            average_concurrency_display=_number(throughput.average_concurrency),
            peak_concurrency=throughput.peak_concurrency,
            median_queue_wait_seconds=throughput.median_queue_wait_seconds,
            median_queue_wait_display=format_duration_seconds(throughput.median_queue_wait_seconds),
            p90_queue_wait_seconds=throughput.p90_queue_wait_seconds,
            p90_queue_wait_display=format_duration_seconds(throughput.p90_queue_wait_seconds),
            queue_waits_measured=throughput.queue_waits_measured,
            scope=(
                f"Every execution running at any time in {days}, time-weighted over the "
                "window. Queue wait is request to start, for executions that started in the "
                "window and were requested through the queue."
            ),
        ),
        total_cost_usd=str(card.total_cost_usd),
        total_cost_display=format_cost(card.total_cost_usd),
        cost_scope=(
            f"Lane-2 cost of all {card.executions_in_chains} executions in those chains, "
            f"failed and superseded runs included; {card.executions_costed} had cost recorded."
        ),
        delivery=ScorecardDeliveryResponse(
            merged_prs=card.merged_prs,
            cost_per_merged_pr_usd=(
                None if card.cost_per_merged_pr_usd is None else str(card.cost_per_merged_pr_usd)
            ),
            cost_per_merged_pr_display=format_cost(card.cost_per_merged_pr_usd),
            scope=card.merged_pr_scope,
        ),
        targets=[_target(t) for t in card.targets],
        eval_quality_scope=(
            "Not shown: eval pass rate per eval x variant needs a definition of a pass, "
            "which no event records yet."
        ),
    )
