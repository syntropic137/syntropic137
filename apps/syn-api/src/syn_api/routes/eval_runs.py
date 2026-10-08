"""An eval's runs as data points: membership, observed models, cost, score (Evals v2).

Three sources, joined here at read time and nowhere else:

- WHICH executions are runs: the execution list filtered by ``eval_id``, the
  same rows ``GET /executions?eval_id=`` serves (membership truth stays on the
  execution's own stream);
- WHAT each run did - the model each phase actually ran, its cost and
  duration: ``get_detail``, the loader behind ``GET /executions/{id}``. The
  observed model is Lane 2 telemetry (session cost), so no event-store
  projection can hold it; reading it through the execution detail means an eval
  run and its execution page cannot name different models;
- HOW it was judged: the run's current score, from the eval read model.

``summarize`` (domain) then decides pass rate and variants from those facts.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from syn_api.model_identity import UNKNOWN_MODEL_KEY
from syn_api.routes.executions.queries import get_detail
from syn_api.types import (
    EvalRunListResponse,
    EvalRunModelResponse,
    EvalRunResponse,
    EvalVariantResponse,
    ExecutionEvalRunResponse,
    Ok,
)
from syn_domain.contexts.orchestration import ExecutionListReads
from syn_domain.contexts.orchestration.domain.read_models.eval_runs import (
    EvalRunFacts,
    EvalRunsSummary,
    PhaseModel,
    summarize,
)
from syn_domain.contexts.orchestration.slices.list_evals.projection import EvalListProjection
from syn_shared.display.formatters import EM_DASH, format_cost, format_duration_seconds

if TYPE_CHECKING:
    from collections.abc import Iterable

    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
    from syn_adapters.projections.manager import ProjectionManager
    from syn_api.types import PhaseExecution
    from syn_domain.contexts.orchestration.domain.read_models.eval_runs import EvalRunScore
    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
        WorkflowExecutionSummary,
    )

#: How much of a score's markdown evidence a run row carries.
EVIDENCE_EXCERPT_CHARS = 280


def _iso(value: datetime | str | None) -> str | None:
    """The read model stores ISO strings; a datetime is rendered the same way."""
    return value.isoformat() if isinstance(value, datetime) else value


def _cost(value: Decimal | str) -> Decimal | None:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _phase_models(phase: PhaseExecution) -> tuple[PhaseModel, ...]:
    """Every model the phase was observed running, sorted: its own and its delegates'.

    The phase's own reported model is always in, priced or not. ``cost_by_model``
    (the per-model split of the phase's Lane 2 cost) adds its delegates' models:
    a codex phase that delegated to claude ran both. Its unknown bucket is not a
    model and is dropped. Known limit: the split holds only PRICED rows, so a
    delegate whose model has no rate and no SDK cost is not seen here (#1743).
    """
    observed = {key for key in phase.cost_by_model if key != UNKNOWN_MODEL_KEY}
    if phase.model:
        observed.add(str(phase.model))
    return tuple(PhaseModel(phase.phase_id, model) for model in sorted(observed))


async def _facts(row: WorkflowExecutionSummary, scores: dict[str, EvalRunScore]) -> EvalRunFacts:
    """One member row, with what its phases ran and what it cost."""
    execution_id = row.workflow_execution_id
    detail = await get_detail(execution_id)
    if isinstance(detail, Ok):
        full = detail.value
        models = tuple(m for p in full.phases for m in _phase_models(p))
        cost = _cost(full.total_cost_usd)
        duration = full.total_duration_seconds
    else:
        models, cost, duration = (), None, None
    return EvalRunFacts(
        execution_id=execution_id,
        workflow_id=row.workflow_id,
        workflow_version=row.workflow_version,
        status=row.status,
        started_at=_iso(row.started_at),
        completed_at=_iso(row.completed_at),
        models=models,
        total_cost_usd=cost,
        duration_seconds=duration,
        score=scores.get(execution_id),
    )


async def eval_run_facts(
    manager: ProjectionManager,
    eval_id: str,
    *,
    statuses: list[str] | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> tuple[list[EvalRunFacts], int]:
    """A page of the eval's current runs, newest first, and how many it has in all."""
    members = await manager.eval_list.members(
        eval_id, statuses=statuses, offset=offset, limit=limit
    )
    scores = await manager.eval_list.scores(eval_id)
    return [await _facts(row, scores) for row in members.rows], members.total


async def eval_summary(manager: ProjectionManager, eval_id: str) -> EvalRunsSummary:
    """Pass rate, newest verdict and variants over every current run of the eval."""
    runs, _total = await eval_run_facts(manager, eval_id)
    return summarize(runs)


def pass_rate_display(rate: float | None) -> str:
    return EM_DASH if rate is None else f"{rate:.0%}"


def variant_responses(summary: EvalRunsSummary) -> list[EvalVariantResponse]:
    return [
        EvalVariantResponse(
            workflow_id=v.workflow_id,
            workflow_version=v.workflow_version,
            models=list(v.models),
            run_count=v.run_count,
            pass_count=v.pass_count,
            pass_rate=v.pass_rate,
            pass_rate_display=pass_rate_display(v.pass_rate),
            avg_cost_usd=v.avg_cost_usd,
            avg_cost_display=format_cost(v.avg_cost_usd),
            last_run_at=v.last_run_at,
        )
        for v in summary.variants
    ]


def _run_response(run: EvalRunFacts) -> EvalRunResponse:
    score = run.score
    return EvalRunResponse(
        execution_id=run.execution_id,
        started_at=run.started_at,
        completed_at=run.completed_at,
        status=run.status,
        workflow_id=run.workflow_id,
        workflow_version=run.workflow_version,
        models=[EvalRunModelResponse(phase_id=m.phase_id, model=m.model) for m in run.models],
        total_cost_usd=run.total_cost_usd,
        total_cost_display=format_cost(run.total_cost_usd),
        duration_seconds=run.duration_seconds,
        duration_display=format_duration_seconds(run.duration_seconds),
        verdict=None if score is None else score.verdict,
        score=None if score is None else score.score,
        evidence_excerpt=None if score is None else score.evidence[:EVIDENCE_EXCERPT_CHARS],
        scorer=None if score is None else score.scorer,
        scorer_version=None if score is None else score.scorer_version,
        scored_at=None if score is None else score.scored_at,
    )


async def eval_run_page(
    manager: ProjectionManager,
    eval_id: str,
    *,
    page: int,
    page_size: int,
    statuses: list[str] | None = None,
) -> EvalRunListResponse:
    """One page of the eval's runs. An unknown eval is an empty page."""
    runs, total = await eval_run_facts(
        manager, eval_id, statuses=statuses, offset=(page - 1) * page_size, limit=page_size
    )
    return EvalRunListResponse(
        items=[_run_response(run) for run in runs], total=total, page=page, page_size=page_size
    )


async def execution_eval_run(
    store: ProjectionStoreProtocol, execution_id: str
) -> ExecutionEvalRunResponse | None:
    """The eval the execution is a current run of, with its current verdict.

    Membership is the execution list's row (the same ``eval_id`` the runs view
    filters on), so this and ``GET /evals/{id}/runs`` cannot disagree about
    whether the execution is a run. Read from the store the execution detail
    route already holds, like its resume-start record. None in no eval.
    """
    row = await ExecutionListReads(store).get_by_id(execution_id)
    if row is None:
        return None
    return (await execution_eval_runs(store, [row])).get(execution_id)


async def execution_eval_runs(
    store: ProjectionStoreProtocol, rows: Iterable[WorkflowExecutionSummary]
) -> dict[str, ExecutionEvalRunResponse]:
    """The eval each execution row is a current run of, with its verdict, by execution id.

    Two reads for any number of rows, one for the evals' names and one for the
    runs' scores, so a page of executions costs what one execution costs.
    Rows in no eval are omitted.
    """
    runs = {
        row.workflow_execution_id: (row.eval_id, kind)
        for row in rows
        if row.eval_id is not None and (kind := row.association_kind) in ("launched", "attached")
    }
    if not runs:
        return {}
    evals = EvalListProjection(store)
    records = await evals.records({eval_id for eval_id, _ in runs.values()})
    scores = await evals.scores_of(
        {(eval_id, execution_id) for execution_id, (eval_id, _) in runs.items()}
    )
    responses: dict[str, ExecutionEvalRunResponse] = {}
    for execution_id, (eval_id, kind) in runs.items():
        record = records.get(eval_id)
        score = scores.get((eval_id, execution_id))
        responses[execution_id] = ExecutionEvalRunResponse(
            eval_id=eval_id,
            eval_name=None if record is None else record.name,
            association_kind="launched" if kind == "launched" else "attached",
            verdict=None if score is None else score.verdict,
            score=None if score is None else score.score,
            scored_at=None if score is None else score.scored_at,
        )
    return responses
