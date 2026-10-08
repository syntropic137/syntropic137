"""The platform scorecard: what a window of runs achieved and what it cost.

Pure: given the window's run records and their Lane-2 costs, it decides every
number. The API reads the inputs and renders the result; it decides nothing.

Every count is over RESUME CHAINS, not executions. A chain is an execution and
every resume of it; its outcome is its final run's, and it is in the window when
that final run ended in the window. Its cost is the cost of every run in it,
failed and superseded ones included, wherever in time they ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)
from syn_domain.contexts.orchestration.slices.scorecard.phase_type import PhaseType
from syn_domain.contexts.orchestration.slices.scorecard.projection import day_key
from syn_domain.contexts.orchestration.slices.scorecard.run_record import (
    RunOutcome,
    ScorecardRun,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syn_domain.contexts.orchestration.slices.scorecard.run_record import (
        MergedPullRequest,
        ScorecardPhase,
    )

# The owner's one-week go/no-go, 2026-10-07 -> 2026-10-14.
TARGET_PLATFORM_FAILURE_FREE_RATE = 0.85
TARGET_MEDIAN_VERIFY_TOKENS = 3_000_000
TARGET_COST_PER_MERGED_PR_USD = Decimal("5")
TARGET_CONCURRENCY = 20

MERGED_PR_SCOPE = (
    "PRs merged in the window. A PR's cost is every execution recorded as "
    "contributing to it - failed, resumed and reverify runs included, each once "
    "- wherever in time it ran. Attributed from the PR a run was started on, "
    "continued, or had open from a branch its failure observed (#1728)."
)


def percentile[T: (float, Decimal)](values: Sequence[T], fraction: float) -> T | None:
    """Nearest-rank percentile; None for no values, never a made-up zero."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-int(fraction * 100) * len(ordered) // 100))
    return ordered[min(rank, len(ordered)) - 1]


@dataclass(frozen=True)
class OutcomeCounts:
    completed: int = 0
    failed_platform: int = 0
    failed_task: int = 0
    failed_correct_refusal: int = 0
    failed_unclassified: int = 0
    cancelled: int = 0
    completed_platform_failure_free: int = 0

    @property
    def total(self) -> int:
        return (
            self.completed
            + self.failed_platform
            + self.failed_task
            + self.failed_correct_refusal
            + self.failed_unclassified
            + self.cancelled
        )

    @property
    def platform_failure_free_rate(self) -> float | None:
        """Chains that completed and never failed on the platform, over chains
        that finished other than by cancellation. None when there are none."""
        denominator = self.total - self.cancelled
        return self.completed_platform_failure_free / denominator if denominator else None


@dataclass(frozen=True)
class ExecutionSpend:
    """One execution's Lane-2 cost: its total, and the part of it each phase_id spent."""

    total_usd: Decimal
    by_phase: Mapping[str, Decimal]


@dataclass(frozen=True)
class OutcomeRow:
    key: str
    counts: OutcomeCounts
    phases: tuple[PhaseTypeStats, ...] = ()


@dataclass(frozen=True)
class PhaseTypeStats:
    phase_type: PhaseType
    phase_count: int
    median_tokens: float | None
    p90_tokens: float | None
    cache_read_share: float | None
    median_tool_calls: float | None
    tokens_per_tool_call: float | None
    phases_with_tool_counts: int
    median_cost_usd: Decimal | None
    p90_cost_usd: Decimal | None
    phases_with_cost: int
    """Phases whose execution recorded a cost for that phase_id; the cost figures are over these."""


@dataclass(frozen=True)
class DailyPoint:
    day: str
    counts: OutcomeCounts
    cost_usd: Decimal
    median_verify_tokens: float | None
    median_verify_cost_usd: Decimal | None
    peak_concurrency: int
    phases: tuple[PhaseTypeStats, ...] = ()
    by_workflow: tuple[OutcomeRow, ...] = ()
    by_model: tuple[OutcomeRow, ...] = ()


@dataclass(frozen=True)
class Throughput:
    average_concurrency: float
    peak_concurrency: int
    median_queue_wait_seconds: float | None
    p90_queue_wait_seconds: float | None
    queue_waits_measured: int


class TargetStatus(StrEnum):
    ON_TRACK = "on_track"
    OFF_TRACK = "off_track"
    NO_DATA = "no_data"


@dataclass(frozen=True)
class TargetResult:
    name: str
    actual: float | None
    target: float
    higher_is_better: bool
    status: TargetStatus


@dataclass(frozen=True)
class Scorecard:
    window_start: datetime
    window_end: datetime
    window_days: int
    counts: OutcomeCounts
    by_workflow: tuple[OutcomeRow, ...]
    by_model: tuple[OutcomeRow, ...]
    phases: tuple[PhaseTypeStats, ...]
    daily: tuple[DailyPoint, ...]
    throughput: Throughput
    total_cost_usd: Decimal
    executions_costed: int
    executions_in_chains: int
    merged_prs: int | None
    cost_per_merged_pr_usd: Decimal | None
    merged_pr_scope: str
    targets: tuple[TargetResult, ...]


@dataclass(frozen=True)
class _Chain:
    final: ScorecardRun
    members: tuple[ScorecardRun, ...]


def _tally(chains: Sequence[_Chain]) -> OutcomeCounts:
    fields = dict.fromkeys(
        (
            "completed",
            "failed_platform",
            "failed_task",
            "failed_correct_refusal",
            "failed_unclassified",
            "cancelled",
            "completed_platform_failure_free",
        ),
        0,
    )
    for chain in chains:
        final = chain.final
        if final.outcome is RunOutcome.COMPLETED:
            fields["completed"] += 1
            if not any(
                m.failure_classification is FailureClassification.PLATFORM for m in chain.members
            ):
                fields["completed_platform_failure_free"] += 1
        elif final.outcome is RunOutcome.CANCELLED:
            fields["cancelled"] += 1
        elif final.failure_classification is FailureClassification.PLATFORM:
            fields["failed_platform"] += 1
        elif final.failure_classification is FailureClassification.TASK:
            fields["failed_task"] += 1
        elif final.failure_classification is FailureClassification.CORRECT_REFUSAL:
            fields["failed_correct_refusal"] += 1
        else:
            fields["failed_unclassified"] += 1
    return OutcomeCounts(**fields)


def _phase_costs(
    runs: Sequence[ScorecardRun], spend: Mapping[str, ExecutionSpend], phase_type: PhaseType
) -> list[Decimal]:
    """What each phase of this type cost, for the phases whose execution recorded it.

    Keyed by (execution, phase_id), so a failed phase - which has no session on
    the run record - is costed the same way as one that completed.
    """
    costs: list[Decimal] = []
    for run in runs:
        recorded = spend.get(run.execution_id)
        if recorded is None:
            continue
        for p in run.phases:
            if p.phase_type is phase_type and p.phase_id in recorded.by_phase:
                costs.append(recorded.by_phase[p.phase_id])
    return costs


def _phase_stats(
    runs: Sequence[ScorecardRun],
    tool_calls_by_session: Mapping[str, int],
    spend: Mapping[str, ExecutionSpend],
    *,
    model: str | None = None,
    cost_by_session_model: Mapping[str, Mapping[str, Decimal]] | None = None,
) -> tuple[PhaseTypeStats, ...]:
    """Per phase type; with ``model``, only the phases whose session observed it.

    A model's phase cost is what that model cost in the phase's session, not
    the whole phase: a session that observed two models splits its spend.
    """
    observed = cost_by_session_model or {}
    rows: list[PhaseTypeStats] = []
    for phase_type in PhaseType:
        phases = _phases_of(runs, phase_type, model, observed)
        if not phases:
            continue
        costs = (
            _phase_costs(runs, spend, phase_type)
            if model is None
            else [observed[p.session_id or ""][model] for p in phases]
        )
        rows.append(_stats_of(phase_type, phases, costs, tool_calls_by_session))
    return tuple(rows)


def _phases_of(
    runs: Sequence[ScorecardRun],
    phase_type: PhaseType,
    model: str | None,
    observed: Mapping[str, Mapping[str, Decimal]],
) -> list[ScorecardPhase]:
    return [
        p
        for run in runs
        for p in run.phases
        if p.phase_type is phase_type
        and (model is None or model in observed.get(p.session_id or "", {}))
    ]


def _stats_of(
    phase_type: PhaseType,
    phases: Sequence[ScorecardPhase],
    costs: list[Decimal],
    tool_calls_by_session: Mapping[str, int],
) -> PhaseTypeStats:
    tokens = [float(p.total_tokens) for p in phases]
    all_tokens = sum(p.total_tokens for p in phases)
    counted = [
        (p.total_tokens, tool_calls_by_session[p.session_id])
        for p in phases
        if p.session_id and p.session_id in tool_calls_by_session
    ]
    calls = sum(c for _, c in counted)
    return PhaseTypeStats(
        phase_type=phase_type,
        phase_count=len(phases),
        median_tokens=percentile(tokens, 0.5),
        p90_tokens=percentile(tokens, 0.9),
        cache_read_share=(
            sum(p.cache_read_tokens for p in phases) / all_tokens if all_tokens else None
        ),
        median_tool_calls=percentile([float(c) for _, c in counted], 0.5),
        tokens_per_tool_call=(sum(t for t, _ in counted) / calls if calls else None),
        phases_with_tool_counts=len(counted),
        median_cost_usd=percentile(costs, 0.5),
        p90_cost_usd=percentile(costs, 0.9),
        phases_with_cost=len(costs),
    )


def _intervals(
    runs: Sequence[ScorecardRun], start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    spans: list[tuple[datetime, datetime]] = []
    for run in runs:
        if run.started_at is None:
            continue
        lo = max(run.started_at, start)
        hi = min(run.ended_at or end, end)
        if hi > lo:
            spans.append((lo, hi))
    return spans


def _peak(spans: Sequence[tuple[datetime, datetime]]) -> int:
    # Ends sort before starts at the same instant: back-to-back runs are not concurrent.
    edges = sorted([(s, 1) for s, _ in spans] + [(e, -1) for _, e in spans])
    peak = current = 0
    for _, delta in edges:
        current += delta
        peak = max(peak, current)
    return peak


def _target(name: str, actual: float | None, target: float, *, higher: bool) -> TargetResult:
    if actual is None:
        status = TargetStatus.NO_DATA
    elif (actual >= target) if higher else (actual <= target):
        status = TargetStatus.ON_TRACK
    else:
        status = TargetStatus.OFF_TRACK
    return TargetResult(name, actual, target, higher, status)


def _verify_median(runs: Sequence[ScorecardRun]) -> float | None:
    return percentile(
        [
            float(p.total_tokens)
            for run in runs
            for p in run.phases
            if p.phase_type is PhaseType.VERIFY
        ],
        0.5,
    )


def _chain_cost(chain: _Chain, spend: Mapping[str, ExecutionSpend]) -> Decimal:
    return sum(
        (spend[m.execution_id].total_usd for m in chain.members if m.execution_id in spend),
        Decimal(0),
    )


def _chains_ended_between(
    runs: Mapping[str, ScorecardRun], start: datetime, end: datetime
) -> list[_Chain]:
    """Every chain whose final run ended in [start, end], with the members we hold."""
    return [
        _Chain(run, tuple(runs[i] for i in run.chain if i in runs))
        for run in runs.values()
        if run.is_final
        and run.outcome is not RunOutcome.RUNNING
        and run.ended_at is not None
        and start <= run.ended_at <= end
    ]


def _observed_models(
    chain: _Chain, cost_by_session_model: Mapping[str, Mapping[str, Decimal]]
) -> dict[str, None]:
    """Every model a phase session of this chain observed, in first-seen order."""
    return dict.fromkeys(
        m
        for member in chain.members
        for p in member.phases
        for m in cost_by_session_model.get(p.session_id or "", {})
    )


def _breakdown(
    chains: Sequence[_Chain],
    tool_calls_by_session: Mapping[str, int],
    spend: Mapping[str, ExecutionSpend],
    *,
    cost_by_session_model: Mapping[str, Mapping[str, Decimal]] | None = None,
) -> tuple[OutcomeRow, ...]:
    """By workflow, or by observed model when ``cost_by_session_model`` is given.

    By model, a chain's OUTCOME counts under every model one of its phases
    observed (a mixed-model chain is one outcome for each), while its PHASES
    count only under the models their own session observed.
    """
    groups: dict[str, list[_Chain]] = {}
    for chain in chains:
        keys = (
            _observed_models(chain, cost_by_session_model)
            if cost_by_session_model is not None
            else (chain.final.workflow_name or chain.final.workflow_id,)
        )
        for key in keys:
            groups.setdefault(key, []).append(chain)
    return tuple(
        OutcomeRow(
            k,
            _tally(v),
            _phase_stats(
                [m for c in v for m in c.members],
                tool_calls_by_session,
                spend,
                model=k if cost_by_session_model is not None else None,
                cost_by_session_model=cost_by_session_model,
            ),
        )
        for k, v in sorted(groups.items())
    )


def _throughput(runs: Sequence[ScorecardRun], start: datetime, end: datetime) -> Throughput:
    spans = _intervals(runs, start, end)
    window_seconds = (end - start).total_seconds()
    waits = [
        (run.started_at - run.requested_at).total_seconds()
        for run in runs
        if run.requested_at is not None
        and run.started_at is not None
        and start <= run.started_at <= end
    ]
    return Throughput(
        average_concurrency=(
            sum((hi - lo).total_seconds() for lo, hi in spans) / window_seconds
            if window_seconds > 0
            else 0.0
        ),
        peak_concurrency=_peak(spans),
        median_queue_wait_seconds=percentile(waits, 0.5),
        p90_queue_wait_seconds=percentile(waits, 0.9),
        queue_waits_measured=len(waits),
    )


def _daily(
    chains: Sequence[_Chain],
    started: Sequence[ScorecardRun],
    spend: Mapping[str, ExecutionSpend],
    start: datetime,
    end: datetime,
    window_days: int,
    *,
    tool_calls_by_session: Mapping[str, int],
    cost_by_session_model: Mapping[str, Mapping[str, Decimal]],
) -> tuple[DailyPoint, ...]:
    """One point per UTC day, from the chains whose final run ended that day.

    Each day's phase, workflow and model statistics are computed by the same
    functions as the window's, over that day's chains only, so a day's
    distribution is its own and the days partition the window's chains.
    """
    points: list[DailyPoint] = []
    for i in range(window_days):
        day_start = start + timedelta(days=i)
        day = day_key(day_start)
        day_chains = [c for c in chains if c.final.ended_at and day_key(c.final.ended_at) == day]
        day_members = [m for c in day_chains for m in c.members]
        points.append(
            DailyPoint(
                day=day,
                counts=_tally(day_chains),
                cost_usd=sum((_chain_cost(c, spend) for c in day_chains), Decimal(0)),
                median_verify_tokens=_verify_median([m for c in day_chains for m in c.members]),
                median_verify_cost_usd=percentile(
                    _phase_costs(
                        [m for c in day_chains for m in c.members], spend, PhaseType.VERIFY
                    ),
                    0.5,
                ),
                peak_concurrency=_peak(
                    _intervals(started, day_start, min(day_start + timedelta(days=1), end))
                ),
                phases=_phase_stats(day_members, tool_calls_by_session, spend),
                by_workflow=_breakdown(day_chains, tool_calls_by_session, spend),
                by_model=_breakdown(
                    day_chains,
                    tool_calls_by_session,
                    spend,
                    cost_by_session_model=cost_by_session_model,
                ),
            )
        )
    return tuple(points)


def merged_pull_request_cost(pr: MergedPullRequest, spend: Mapping[str, ExecutionSpend]) -> Decimal:
    """Every contributing execution's cost, each counted once."""
    contributors = dict.fromkeys(pr.execution_ids)
    return sum(
        (spend[e].total_usd for e in contributors if e in spend),
        Decimal(0),
    )


def _merged_in(
    merged: Sequence[MergedPullRequest], start: datetime, end: datetime
) -> list[MergedPullRequest]:
    unique = {pr.key: pr for pr in merged}
    return [pr for pr in unique.values() if start <= pr.merged_at.astimezone(UTC) <= end]


def _cost_per_merged_pr(
    merged: Sequence[MergedPullRequest], spend: Mapping[str, ExecutionSpend]
) -> Decimal | None:
    if not merged:
        return None
    total = sum((merged_pull_request_cost(pr, spend) for pr in merged), Decimal(0))
    return total / len(merged)


def _targets(
    counts: OutcomeCounts,
    verify_median: float | None,
    throughput: Throughput,
    *,
    ran: bool,
    cost_per_merged_pr: Decimal | None,
) -> tuple[TargetResult, ...]:
    return (
        _target(
            "Platform-failure-free completion",
            counts.platform_failure_free_rate,
            TARGET_PLATFORM_FAILURE_FREE_RATE,
            higher=True,
        ),
        _target("Median verify tokens", verify_median, TARGET_MEDIAN_VERIFY_TOKENS, higher=False),
        _target(
            "Cost per merged PR (USD)",
            None if cost_per_merged_pr is None else float(cost_per_merged_pr),
            float(TARGET_COST_PER_MERGED_PR_USD),
            higher=False,
        ),
        _target(
            "Stable concurrency",
            throughput.average_concurrency if ran else None,
            TARGET_CONCURRENCY,
            higher=True,
        ),
    )


def compute_scorecard(
    *,
    runs: Mapping[str, ScorecardRun],
    spend_by_execution: Mapping[str, ExecutionSpend],
    tool_calls_by_session: Mapping[str, int],
    cost_by_session_model: Mapping[str, Mapping[str, Decimal]],
    now: datetime,
    window_days: int,
    merged_pull_requests: Sequence[MergedPullRequest] = (),
) -> Scorecard:
    """Score the ``window_days`` UTC days ending now.

    ``runs`` must hold every run that ended in the window, every run still
    running, and every member of their resume chains, keyed by execution id.
    ``cost_by_session_model`` is each phase session's Lane-2 cost by the model
    the harness REPORTED; aliases and unknown models must already be excluded.
    ``merged_pull_requests`` must hold every PR merged in the window, and
    ``spend_by_execution`` every one of their contributors.
    """
    today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=window_days - 1)
    chains = _chains_ended_between(runs, start, now)
    members = [m for chain in chains for m in chain.members]
    started = [run for run in runs.values() if run.started_at is not None]
    counts = _tally(chains)
    throughput = _throughput(started, start, now)
    merged = _merged_in(merged_pull_requests, start, now)
    cost_per_merged_pr = _cost_per_merged_pr(merged, spend_by_execution)

    return Scorecard(
        window_start=start,
        window_end=now,
        window_days=window_days,
        counts=counts,
        by_workflow=_breakdown(chains, tool_calls_by_session, spend_by_execution),
        by_model=_breakdown(
            chains,
            tool_calls_by_session,
            spend_by_execution,
            cost_by_session_model=cost_by_session_model,
        ),
        phases=_phase_stats(members, tool_calls_by_session, spend_by_execution),
        daily=_daily(
            chains,
            started,
            spend_by_execution,
            start,
            now,
            window_days,
            tool_calls_by_session=tool_calls_by_session,
            cost_by_session_model=cost_by_session_model,
        ),
        throughput=throughput,
        total_cost_usd=sum((_chain_cost(c, spend_by_execution) for c in chains), Decimal(0)),
        executions_costed=sum(1 for m in members if m.execution_id in spend_by_execution),
        executions_in_chains=len(members),
        merged_prs=len(merged),
        cost_per_merged_pr_usd=cost_per_merged_pr,
        merged_pr_scope=MERGED_PR_SCOPE,
        targets=_targets(
            counts,
            _verify_median(members),
            throughput,
            ran=bool(_intervals(started, start, now)),
            cost_per_merged_pr=cost_per_merged_pr,
        ),
    )
