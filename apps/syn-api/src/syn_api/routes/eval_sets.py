"""An eval set's trial figures over HTTP: pass@k, pass^k, flakiness, infra errors bounded (#2108).

Every number is computed by the domain read model (``eval_sets``,
``eval_trial_metrics``, ``eval_set_comparison``) at query time, from the same
run facts ``GET /evals/{id}/runs`` reads (``RunReads``). This module only reads
the sources and maps the domain's figures onto response models: no math here,
in the CLI or in the UI.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

from syn_api._wiring import ensure_connected, get_projection_mgr
from syn_api.routes.eval_runs import RunReads, baseline_pins, eval_run_facts, pass_rate_display
from syn_api.types import (
    EvalBoundsResponse,
    EvalCaseCohortResponse,
    EvalCaseMetricsResponse,
    EvalCohortKeyResponse,
    EvalImageManifestResponse,
    EvalIntervalResponse,
    EvalRosterCaseResponse,
    EvalSetCohortResponse,
    EvalSetComparisonResponse,
    EvalSetCoverageResponse,
    EvalSetMetricsResponse,
)
from syn_domain.contexts.orchestration import (
    EvalTag,
    TaggedEval,
    compare_pair,
    roster_of,
    summarize_case,
    summarize_eval_set,
)

if TYPE_CHECKING:
    from syn_adapters.projections.manager import ProjectionManager
    from syn_domain.contexts.orchestration.domain.read_models.eval_set_comparison import (
        Interval,
        PairedComparison,
    )
    from syn_domain.contexts.orchestration.domain.read_models.eval_sets import (
        CohortSummary,
        EvalSetSummary,
    )
    from syn_domain.contexts.orchestration.domain.read_models.eval_trial_metrics import (
        Bounds,
        CaseMetrics,
    )
    from syn_domain.contexts.orchestration.domain.read_models.eval_trials import CohortKey

router = APIRouter(tags=["evals"])

MAX_EVAL_SET_CASES = 500
"""The most evals one set read loads. A larger roster is refused, never truncated:
a figure over part of a roster would read as the whole one."""
MAX_EVAL_SET_RUNS = 5_000
"""The most member runs one set or cohort read loads; refused past it, never truncated."""


def _too_large(what: str, count: int, limit: int) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail=f"{what} has {count}, more than the {limit} one metrics read loads; "
        "narrow it (e.g. by split) rather than read part of it",
    )


def _bounds(bounds: Bounds) -> EvalBoundsResponse:
    return EvalBoundsResponse(
        lower=bounds.lower,
        upper=bounds.upper,
        display=f"{pass_rate_display(bounds.lower)} to {pass_rate_display(bounds.upper)}",
    )


def _cohort(key: CohortKey) -> EvalCohortKeyResponse:
    return EvalCohortKeyResponse(
        suite_version=key.suite_version,
        workflow_id=key.workflow_id,
        workflow_version=key.workflow_version,
        models_digest=key.models_digest,
        scorer_protocol=key.scorer_protocol,
    )


def case_metrics_response(m: CaseMetrics) -> EvalCaseMetricsResponse:
    return EvalCaseMetricsResponse(
        eval_id=m.eval_id,
        k=m.k,
        n=m.counts.judged,
        c=m.counts.passes,
        pending=m.counts.pending,
        infra_error_count=m.counts.infra_errors,
        base_mismatch_count=m.counts.base_mismatch,
        treatment_mismatch_count=m.counts.treatment_mismatch,
        trials_short=m.trials_short,
        exhausted=m.exhausted,
        complete=m.complete,
        never_launched=m.never_launched,
        pass_at_k=m.pass_at_k,
        pass_at_k_display=pass_rate_display(m.pass_at_k),
        pass_hat_k=m.pass_hat_k,
        pass_hat_k_display=pass_rate_display(m.pass_hat_k),
        flaky=m.flaky,
        pass_at_k_bounds=_bounds(m.pass_at_k_bounds),
        pass_hat_k_bounds=_bounds(m.pass_hat_k_bounds),
    )


def _cohort_summary(s: CohortSummary) -> EvalSetCohortResponse:
    return EvalSetCohortResponse(
        cohort=_cohort(s.cohort),
        k=s.k,
        cases=[case_metrics_response(c) for c in s.cases],
        coverage=EvalSetCoverageResponse(
            roster_size=s.coverage.roster_size,
            complete=s.coverage.complete,
            short=s.coverage.short,
            never_launched=s.coverage.never_launched,
        ),
        mean_pass_at_k=s.mean_pass_at_k,
        mean_pass_at_k_display=pass_rate_display(s.mean_pass_at_k),
        mean_pass_hat_k=s.mean_pass_hat_k,
        mean_pass_hat_k_display=pass_rate_display(s.mean_pass_hat_k),
        flakiness=s.flakiness,
        partial=s.partial,
        flaky_cases=list(s.flaky_cases),
        pass_at_k_bounds=_bounds(s.pass_at_k_bounds),
        pass_hat_k_bounds=_bounds(s.pass_hat_k_bounds),
        infra_error_count=s.infra_error_count,
        infra_share=s.infra_share,
        base_mismatch_count=s.base_mismatch_count,
        treatment_mismatch_count=s.treatment_mismatch_count,
        image_manifests=[
            EvalImageManifestResponse.model_validate(m.model_dump()) for m in s.images.manifests
        ],
        trials_without_image_manifest=s.images.trials_without_manifest,
    )


def _interval(interval: Interval | None) -> EvalIntervalResponse | None:
    if interval is None:
        return None
    return EvalIntervalResponse(estimate=interval.estimate, low=interval.low, high=interval.high)


def _comparison(p: PairedComparison | None) -> EvalSetComparisonResponse | None:
    if p is None:
        return None
    return EvalSetComparisonResponse(
        a=_cohort(p.a),
        b=_cohort(p.b),
        k=p.k,
        paired_cases=list(p.paired_cases),
        short_cases=list(p.short_cases),
        coverage_complete=p.coverage_complete,
        a_only=p.a_only,
        b_only=p.b_only,
        both=p.both,
        neither=p.neither,
        mcnemar_p=p.mcnemar_p,
        difference=_interval(p.difference),
        a_lower_minus_b_upper=_interval(p.a_lower_minus_b_upper),
        a_upper_minus_b_lower=_interval(p.a_upper_minus_b_lower),
    )


def eval_set_response(summary: EvalSetSummary, k: int) -> EvalSetMetricsResponse:
    roster = summary.roster
    return EvalSetMetricsResponse(
        suite=roster.suite,
        version=roster.version,
        split=roster.split,
        k=k,
        roster=[
            EvalRosterCaseResponse(eval_id=c.eval_id, split=c.split, polarity=c.polarity)
            for c in roster.cases
        ],
        cohorts=[_cohort_summary(c) for c in summary.cohorts],
        comparison=_comparison(compare_pair(summary)),
        not_a_trial_count=summary.not_a_trial_count,
    )


async def eval_set_summary(
    manager: ProjectionManager, suite: str, version: str, split: str | None, k: int
) -> EvalSetSummary:
    """The roster of ``suite`` version ``version`` and every cohort's figures over it.

    Each source is read once for the whole roster, never per case or run (#1811).
    Every read is bounded: a roster over ``MAX_EVAL_SET_CASES`` evals, or whose
    evals hold over ``MAX_EVAL_SET_RUNS`` runs (counted from the eval rows,
    before any run is loaded), is refused with 422. The figures are computed
    off the event loop: the paired comparison bootstraps.
    """
    tags = [f"{EvalTag.SUITE}:{suite}", f"{EvalTag.SUITE_VERSION}:{version}"]
    evals = await manager.eval_list.page(tags=tags, limit=MAX_EVAL_SET_CASES)
    if evals.total > MAX_EVAL_SET_CASES:
        raise _too_large(f"eval set {suite} v{version}", evals.total, MAX_EVAL_SET_CASES)
    records = {row.record.eval_id: row.record for row in evals.rows}
    roster = roster_of(
        (TaggedEval(r.eval_id, r.tags) for r in records.values()), suite, version, split
    )
    eval_ids = [c.eval_id for c in roster.cases]
    run_counts = {row.record.eval_id: row.run_count for row in evals.rows}
    if (runs := sum(run_counts[e] for e in eval_ids)) > MAX_EVAL_SET_RUNS:
        raise _too_large(f"eval set {suite} v{version}", runs, MAX_EVAL_SET_RUNS)
    members = await manager.eval_list.members_of(eval_ids)
    scores = await manager.eval_list.scores_in(eval_ids)
    execution_ids = {row.workflow_execution_id for rows in members.values() for row in rows}
    reads = await RunReads.load(manager, sorted(execution_ids))
    runs_by_eval = {
        eval_id: [
            reads.facts(
                row,
                scores.get((eval_id, row.workflow_execution_id)),
                baseline_pins(records.get(eval_id)),
            )
            for row in rows
        ]
        for eval_id, rows in members.items()
    }
    return await asyncio.to_thread(summarize_eval_set, roster, runs_by_eval, k)


async def eval_case_cohorts(
    manager: ProjectionManager, eval_id: str, k: int
) -> list[EvalCaseCohortResponse]:
    """One eval's figures in every cohort it has trials in; refused past ``MAX_EVAL_SET_RUNS``."""
    runs, total = await eval_run_facts(manager, eval_id, limit=MAX_EVAL_SET_RUNS)
    if total > MAX_EVAL_SET_RUNS:
        raise _too_large(f"eval {eval_id}", total, MAX_EVAL_SET_RUNS)
    cohorts = await asyncio.to_thread(summarize_case, eval_id, runs, k)
    return [
        EvalCaseCohortResponse(cohort=_cohort(c.cohort), metrics=case_metrics_response(c.metrics))
        for c in cohorts
    ]


@router.get("/eval-sets/metrics", response_model=EvalSetMetricsResponse)
async def get_eval_set_metrics_endpoint(
    suite: str = Query(..., min_length=1, description="The eval set: evals tagged suite:<suite>"),
    version: str = Query(
        ..., min_length=1, description="The roster version: evals tagged suite-version:<version>"
    ),
    k: int = Query(..., ge=1, description="Trials per case the figures are computed over"),
    split: str | None = Query(None, description="Keep only cases of this split, e.g. holdout"),
) -> EvalSetMetricsResponse:
    """pass@k, pass^k and flakiness of every cohort over one eval-set roster (#2108).

    One block per cohort (suite version, workflow and version, declared
    models, scoring protocol), each with per-case rows, coverage, roster-wide
    bounds with infra errors and missing trials counted both ways, and the
    images its trials ran. When exactly two cohorts launched into the roster,
    a paired comparison is added. An unknown suite is an empty roster.
    """
    await ensure_connected()
    manager = get_projection_mgr()
    summary = await eval_set_summary(manager, suite, version, split, k)
    # compare_pair runs three bootstraps: keep them off the event loop.
    return await asyncio.to_thread(eval_set_response, summary, k)
