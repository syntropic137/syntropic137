"""An eval's runs as data points: membership, observed models, cost, score (Evals v2).

Three sources, joined here at read time and nowhere else:

- WHICH executions are runs: the execution list filtered by ``eval_id``, the
  same rows ``GET /executions?eval_id=`` serves (membership truth stays on the
  execution's own stream);
- WHAT each run did - the model each phase actually ran, its cost and
  duration: the execution detail read model plus the Lane 2 session and
  execution costs, the same three sources ``GET /executions/{id}`` reads and
  derived by the same rules (``observed_model_of``, ``cost_by_observed_model``,
  ``models_by_phase`` over the session's split). The observed model is Lane 2
  telemetry, so no event-store projection can hold it;
  ``test_1811_eval_list_reads_runs_in_batches`` pins that a run here and its
  execution page name the same models;
- HOW it was judged: the run's current score, from the eval read model.

Every source is read ONCE per request for every run on it, never per run or
per phase (#1811): the list used to load each run's full execution detail
(event-store query, aggregate replay, a tool timeline and a session cost per
phase) one run at a time, and 88 evals took 24.5 s.

``summarize`` (domain) then decides pass rate and variants from those facts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from syn_api.model_identity import UNKNOWN_MODEL_KEY, cost_by_observed_model, observed_model_of
from syn_api.routes.executions.queries import DurationTotal, phase_duration
from syn_api.types import (
    EvalRunListResponse,
    EvalRunModelResponse,
    EvalRunResponse,
    EvalRunStatsResponse,
    EvalVariantResponse,
    ExecutionEvalRunResponse,
)
from syn_domain.contexts.orchestration import ExecutionListReads
from syn_domain.contexts.orchestration.domain.read_models.eval_runs import (
    EvalRunFacts,
    EvalRunsSummary,
    EvalRunStats,
    PhaseModel,
    summarize,
)
from syn_domain.contexts.orchestration.slices.list_evals.projection import EvalListProjection
from syn_domain.storable_text import pg_safe
from syn_shared.display.formatters import EM_DASH, format_cost, format_duration_seconds

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
    from syn_adapters.projections.manager import ProjectionManager
    from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
    from syn_domain.contexts.orchestration.domain.read_models.eval_runs import EvalRunScore
    from syn_domain.contexts.orchestration.domain.read_models.execution_cost import (
        ExecutionCost,
    )
    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
        PhaseExecutionDetail,
        WorkflowExecutionDetail,
    )
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


def _observed_models(
    phase_id: str, own_model: str | None, cost_by_model: Mapping[str, Decimal]
) -> tuple[PhaseModel, ...]:
    """Every model the phase was observed running, sorted: its own and its delegates'.

    The phase's own reported model is always in, priced or not. ``cost_by_model``
    (the per-model split of the phase's Lane 2 cost) adds its delegates' models:
    a codex phase that delegated to claude ran both. Its unknown bucket is not a
    model and is dropped. Known limit: the split holds only PRICED rows, so a
    delegate whose model has no rate and no SDK cost is not seen here (#1743).
    """
    observed = {key for key in cost_by_model if key != UNKNOWN_MODEL_KEY}
    if own_model:
        observed.add(own_model)
    return tuple(PhaseModel(phase_id, model) for model in sorted(observed))


@dataclass(frozen=True)
class _RunReads:
    """Everything the facts of a set of runs need, each source read once for all of them."""

    details: dict[str, WorkflowExecutionDetail]
    sessions: dict[str, SessionCost]
    """By session id as the detail names it."""
    costs: dict[str, ExecutionCost]
    """By the stored (``pg_safe``) execution id."""

    @classmethod
    async def load(cls, manager: ProjectionManager, execution_ids: Sequence[str]) -> _RunReads:
        details = await manager.workflow_execution_detail.get_many(execution_ids)
        session_ids = [p.session_id for d in details.values() for p in d.phases if p.session_id]
        # Lane 2 fails soft, as on the execution page: a run whose cost cannot
        # be read is reported as one with no cost data, not as an error.
        try:
            sessions = await manager.session_cost.get_session_costs(session_ids)
        except Exception:
            logger.debug("Failed to load session costs for eval runs", exc_info=True)
            sessions = {}
        try:
            read = await manager.execution_cost.list_costs_for_ids(list(details))
            costs = {cost.execution_id: cost for cost in read.costs}
        except Exception:
            logger.debug("Failed to load execution costs for eval runs", exc_info=True)
            costs = {}
        return cls(details=details, sessions=sessions, costs=costs)

    def phase_models(
        self, phase: PhaseExecutionDetail, priced: ExecutionCost | None
    ) -> tuple[PhaseModel, ...]:
        """The models one phase ran, by the rules the execution page applies.

        Own model: the session's OBSERVED model (``observed_model_of``). Split:
        the execution cost's ``models_by_phase`` when it has one for the phase,
        else the session's own (``_enrich_costs`` and ``_load_session_cost``).
        """
        session = self.sessions.get(phase.session_id) if phase.session_id else None
        own = (
            None
            if session is None
            else observed_model_of(session.agent_model, session.requested_model).observed
        )
        split = cost_by_observed_model(session.cost_by_model) if session is not None else {}
        by_phase = priced.models_by_phase.get(phase.workflow_phase_id) if priced else None
        if by_phase:
            split = cost_by_observed_model(by_phase)
        return _observed_models(phase.workflow_phase_id, own, split)

    def facts(self, row: WorkflowExecutionSummary, score: EvalRunScore | None) -> EvalRunFacts:
        """One member row, with what its phases ran and what it cost."""
        execution_id = row.workflow_execution_id
        detail = self.details.get(execution_id)
        if detail is None:
            models: tuple[PhaseModel, ...] = ()
            cost, duration, unpriced, unknown_phases = None, None, 0, 0
        else:
            stored = self.costs.get(pg_safe(execution_id))
            priced = stored if stored is not None and stored.has_cost_data else None
            models = tuple(m for p in detail.phases for m in self.phase_models(p, priced))
            cost = _cost(priced.total_cost_usd) if priced is not None else Decimal(0)
            total = DurationTotal.over(phase_duration(p) for p in detail.phases)
            duration, unknown_phases = total.seconds, total.unknown_phase_count
            unpriced = priced.unpriced_observation_count if priced is not None else 0
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
            score=score,
            unpriced_observation_count=unpriced,
            unknown_duration_phase_count=unknown_phases,
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
    reads = await _RunReads.load(manager, [row.workflow_execution_id for row in members.rows])
    return [
        reads.facts(row, scores.get(row.workflow_execution_id)) for row in members.rows
    ], members.total


async def eval_summaries(
    manager: ProjectionManager, eval_ids: Sequence[str]
) -> dict[str, EvalRunsSummary]:
    """Each eval's summary over every current run, for many evals in a fixed number of reads.

    Every id given gets an entry; an eval with no runs summarizes nothing.
    """
    members = await manager.eval_list.members_of(eval_ids)
    scores = await manager.eval_list.scores_in(eval_ids)
    execution_ids = {row.workflow_execution_id for rows in members.values() for row in rows}
    reads = await _RunReads.load(manager, sorted(execution_ids))
    return {
        eval_id: summarize(
            reads.facts(row, scores.get((eval_id, row.workflow_execution_id))) for row in rows
        )
        for eval_id, rows in members.items()
    }


async def eval_summary(manager: ProjectionManager, eval_id: str) -> EvalRunsSummary:
    """Pass rate, newest verdict and variants over every current run of the eval."""
    return (await eval_summaries(manager, [eval_id]))[eval_id]


def pass_rate_display(rate: float | None) -> str:
    return EM_DASH if rate is None else f"{rate:.0%}"


def _excluding(display: str, incomplete: int) -> str:
    """A median's display, saying how many runs it left out for being incomplete."""
    return f"{display} (excl. {incomplete} incomplete)" if incomplete else display


def _duration_display(seconds: float | None, unknown_phases: int) -> str:
    """A run's duration, marked as a lower bound the way ``format_cost`` marks cost."""
    display = format_duration_seconds(seconds)
    return f">={display} (partial)" if seconds is not None and unknown_phases else display


def stats_response(stats: EvalRunStats) -> EvalRunStatsResponse:
    return EvalRunStatsResponse(
        median_duration_seconds=stats.median_duration_seconds,
        median_duration_display=_excluding(
            format_duration_seconds(stats.median_duration_seconds), stats.incomplete_duration_count
        ),
        incomplete_duration_count=stats.incomplete_duration_count,
        median_cost_usd=stats.median_cost_usd,
        median_cost_display=_excluding(
            format_cost(stats.median_cost_usd), stats.incomplete_cost_count
        ),
        incomplete_cost_count=stats.incomplete_cost_count,
        cost_per_pass_usd=stats.cost_per_pass_usd,
        cost_per_pass_display=format_cost(stats.cost_per_pass_usd, stats.incomplete_spend_count),
    )


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
            last_verdict=v.last_verdict,
            stats=stats_response(v.stats),
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
        total_cost_display=format_cost(run.total_cost_usd, run.unpriced_observation_count),
        duration_seconds=run.duration_seconds,
        duration_display=_duration_display(run.duration_seconds, run.unknown_duration_phase_count),
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
