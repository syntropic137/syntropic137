"""A delegate on a model with no pricing entry is still a model the phase ran (#1743).

``models_by_phase`` decomposes money, so an unpriced row could not appear in it
without a fabricated $0, and the phase's observed models were read from it.
A run whose only difference was such a delegate therefore got the same variant
key as a run without it, and the execution page left the model out entirely.

Each test drives the real chain: Lane 2 rows through ``price_phase_rows``, the
``ExecutionCost`` read model through its stored round trip, then the consumer
(``RunReads`` + ``summarize`` for eval runs, ``_enrich_costs`` for the page).
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_api.routes.eval_runs import RunReads
from syn_api.routes.executions.phase_mapping import _map_phase_to_response
from syn_api.routes.executions.queries import _enrich_costs
from syn_api.types import PhaseExecution
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.orchestration.domain.read_models.eval_runs import summarize
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    PhaseExecutionDetail,
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    price_phase_rows,
)
from syn_shared.display.formatters import UNPRICED

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

LEADER = "gpt-5.6-sol"
#: A reported model id the price table has never heard of, with no SDK cost.
UNPRICED_DELEGATE = "acme-reasoner-7b"
PHASE = "p1"


@dataclass(frozen=True)
class _Row:
    """One Lane 2 phase row, read the way ``price_phase_rows`` reads asyncpg.Record."""

    model: str
    sdk_cost: Decimal | None
    phase_id: str = PHASE
    total_input: int = 1_000
    total_output: int = 1_000
    cache_creation: int = 0
    cache_read: int = 0
    observation_count: int = 1

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)

    def get(self, key: str, default: object = None) -> object:
        return getattr(self, key, default)


def _row(model: str, sdk_cost: str | None) -> _Row:
    return _Row(model=model, sdk_cost=Decimal(sdk_cost) if sdk_cost is not None else None)


def _cache_only_row(model: str) -> _Row:
    """A row with only cache reads, so its execution cost has no ``has_cost_data``."""
    return _Row(model=model, sdk_cost=None, total_input=0, total_output=0, cache_read=1_000)


def _stored_cost(execution_id: str, rows: list[_Row]) -> ExecutionCost:
    """The execution cost as built from Lane 2 rows, then stored and read back."""
    phases = price_phase_rows(rows, CostCalculator())
    built = ExecutionCost(
        execution_id=execution_id,
        total_cost_usd=sum(phases.cost_by_phase.values(), Decimal("0")),
        # Derived from the rows, never hardcoded: ``has_cost_data`` reads these,
        # and a fixed positive pair hid the cache-only case.
        input_tokens=sum(r.total_input for r in rows),
        output_tokens=sum(r.total_output for r in rows),
        cache_read_tokens=sum(r.cache_read for r in rows),
        cost_by_phase=phases.cost_by_phase,
        models_by_phase=phases.models_by_phase,
        observed_models_by_phase=phases.observed_models_by_phase,
        unpriced_by_phase=phases.unpriced_by_phase,
    )
    return ExecutionCost.from_dict(built.to_dict())


def _run(execution_id: str) -> tuple[WorkflowExecutionSummary, WorkflowExecutionDetail]:
    summary = WorkflowExecutionSummary(
        workflow_execution_id=execution_id,
        workflow_id="wf-1",
        workflow_name="wf",
        status="completed",
        started_at="2026-11-01T00:00:00+00:00",
        completed_at="2026-11-01T00:05:00+00:00",
        completed_phases=1,
        total_phases=1,
        total_tokens=0,
        eval_id="eval-1",
        association_kind="launched",
        workflow_version="1",
    )
    detail = WorkflowExecutionDetail(
        workflow_execution_id=execution_id,
        workflow_id="wf-1",
        workflow_name="wf",
        status="completed",
        started_at=summary.started_at,
        completed_at=summary.completed_at,
        phases=(
            PhaseExecutionDetail(
                workflow_phase_id=PHASE,
                name="phase",
                status="completed",
                session_id=f"sess-{execution_id}",
                started_at=summary.started_at,
                completed_at=summary.completed_at,
            ),
        ),
    )
    return summary, detail


def _reads(runs: Mapping[str, list[_Row]]) -> tuple[RunReads, list[WorkflowExecutionSummary]]:
    summaries, details, sessions, costs = [], {}, {}, {}
    for execution_id, rows in runs.items():
        summary, detail = _run(execution_id)
        summaries.append(summary)
        details[execution_id] = detail
        sid = f"sess-{execution_id}"
        sessions[sid] = SessionCost(session_id=sid, agent_model=LEADER, requested_model=None)
        costs[execution_id] = _stored_cost(execution_id, rows)
    return RunReads(details=details, sessions=sessions, costs=costs), summaries


def test_a_phase_whose_only_delegate_is_unpriced_lists_that_model() -> None:
    phases = price_phase_rows([_row(UNPRICED_DELEGATE, None)], CostCalculator())

    assert phases.observed_models_by_phase == {PHASE: [UNPRICED_DELEGATE]}
    # Identity only: no cost, and never a $0 entry in the money split.
    assert phases.cost_by_phase == {}
    assert phases.models_by_phase == {}
    assert phases.unpriced_by_phase == {PHASE: 1}

    reads, (summary,) = _reads({"exec-a": [_row(UNPRICED_DELEGATE, None)]})
    models = {m.model for m in reads.facts(summary, None).models}
    assert models == {LEADER, UNPRICED_DELEGATE}


def test_runs_that_differ_only_by_an_unpriced_delegate_are_different_variants() -> None:
    reads, summaries = _reads(
        {
            "exec-with": [_row(LEADER, "0.19"), _row(UNPRICED_DELEGATE, None)],
            "exec-without": [_row(LEADER, "0.19")],
        }
    )
    summary = summarize(reads.facts(s, None) for s in summaries)

    assert {v.models for v in summary.variants} == {
        (LEADER,),
        tuple(sorted((LEADER, UNPRICED_DELEGATE))),
    }


def test_priced_rows_keep_their_costs_and_reconcile() -> None:
    rows = [_row(LEADER, "0.19"), _row("claude-sonnet-5", "0.03"), _row(UNPRICED_DELEGATE, None)]
    phases = price_phase_rows(rows, CostCalculator())

    assert phases.cost_by_phase == {PHASE: Decimal("0.22")}
    assert phases.models_by_phase == {
        PHASE: {LEADER: Decimal("0.19"), "claude-sonnet-5": Decimal("0.03")}
    }
    assert sum(phases.models_by_phase[PHASE].values()) == phases.cost_by_phase[PHASE]
    assert phases.observed_models_by_phase == {
        PHASE: sorted((LEADER, "claude-sonnet-5", UNPRICED_DELEGATE))
    }


class _CostReader:
    def __init__(self, cost: ExecutionCost) -> None:
        self._cost = cost

    async def get_execution_cost(self, _execution_id: str) -> ExecutionCost:
        return self._cost


class _Manager:
    def __init__(self, cost: ExecutionCost) -> None:
        self.execution_cost = _CostReader(cost)


async def test_the_execution_page_shows_the_unpriced_delegate_as_unpriced() -> None:
    cost = _stored_cost("exec-a", [_row(LEADER, "0.19"), _row(UNPRICED_DELEGATE, None)])
    phase = PhaseExecution(
        phase_id=PHASE,
        name="phase",
        status="completed",
        requested_model=None,
    )

    await _enrich_costs("exec-a", _Manager(cost), [phase], 0, Decimal("0"))
    shown = _map_phase_to_response(phase)

    assert shown.cost_by_model == {LEADER: "0.19"}
    assert shown.unpriced_models == [UNPRICED_DELEGATE]
    assert shown.unpriced_model_cost_display == UNPRICED


def test_a_cache_only_unpriced_delegate_is_still_a_model_the_run_used() -> None:
    reads, summaries = _reads(
        {"exec-with": [_cache_only_row(UNPRICED_DELEGATE)], "exec-without": []}
    )
    assert not reads.costs["exec-with"].has_cost_data

    with_delegate = next(s for s in summaries if s.workflow_execution_id == "exec-with")
    assert {m.model for m in reads.facts(with_delegate, None).models} == {
        LEADER,
        UNPRICED_DELEGATE,
    }
    summary = summarize(reads.facts(s, None) for s in summaries)
    assert {v.models for v in summary.variants} == {
        (LEADER,),
        tuple(sorted((LEADER, UNPRICED_DELEGATE))),
    }


async def test_the_execution_page_shows_a_cache_only_unpriced_delegate() -> None:
    cost = _stored_cost("exec-a", [_cache_only_row(UNPRICED_DELEGATE)])
    assert not cost.has_cost_data
    phase = PhaseExecution(phase_id=PHASE, name="phase", status="completed", requested_model=None)

    enriched = await _enrich_costs("exec-a", _Manager(cost), [phase], 7, Decimal("0.05"))
    shown = _map_phase_to_response(phase)

    # Money keeps its cache-only fallback (#873); identity does not depend on it.
    assert (enriched.total_tokens, enriched.total_cost_usd) == (7, Decimal("0.05"))
    assert shown.cost_by_model == {}
    assert shown.unpriced_models == [UNPRICED_DELEGATE]
    assert shown.unpriced_model_cost_display == UNPRICED
