"""#897 slice L: the execution detail route says what its costs read as.

The dashboard rendered the execution total and every phase card by formatting
``total_cost_usd`` / ``cost_usd`` itself, so the detail page disagreed with the
list, the CLI and the API's own ``format_cost``. The route now carries
``total_cost_display`` and, per phase, ``cost_display``.

WHY THE TEST WALKS THE ROUTE. A phase is built with ``cost_usd=0`` and only
priced afterwards, by ``_enrich_costs`` (#695). A display built anywhere before
that hop reads ``$0.00`` for every phase while ``cost_usd`` beside it is right.
So the cost goes in as Lane 2 data and the display is read off the JSON an API
client receives from ``GET /executions/{id}``.

Every fixture figure is one the default could not produce: ``$0.00`` appears
in no expected value. The queued-start builder is pinned where queued starts
are driven, in ``test_1557_one_execution_budget``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_api.routes.executions.models import ExecutionDetailResponse
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_shared.display import format_cost

pytestmark = pytest.mark.unit

EXECUTION_ID = "exec-897-detail-cost"
PLAN = "phase-plan"
IMPLEMENT = "phase-implement"


@dataclass(frozen=True)
class _Coverage:
    """One execution's Lane 2 cost, and what each figure must render as."""

    name: str
    cost_by_phase: dict[str, Decimal]
    unpriced_by_phase: dict[str, int]
    phase_shows: dict[str, str]
    total: Decimal
    total_unpriced: int
    total_shows: str


CASES = [
    _Coverage(
        name="fully priced",
        cost_by_phase={PLAN: Decimal("0.4213"), IMPLEMENT: Decimal("1.5")},
        unpriced_by_phase={},
        phase_shows={PLAN: "$0.42", IMPLEMENT: "$1.50"},
        total=Decimal("1.9213"),
        total_unpriced=0,
        total_shows="$1.92",
    ),
    _Coverage(
        name="partly unpriced",
        cost_by_phase={PLAN: Decimal("3.5")},
        unpriced_by_phase={IMPLEMENT: 9},
        phase_shows={PLAN: "$3.50", IMPLEMENT: "unpriced"},
        total=Decimal("3.5"),
        total_unpriced=9,
        total_shows=">=$3.50 (partial)",
    ),
    _Coverage(
        name="all unpriced",
        cost_by_phase={},
        unpriced_by_phase={PLAN: 4, IMPLEMENT: 7},
        phase_shows={PLAN: "unpriced", IMPLEMENT: "unpriced"},
        total=Decimal("0"),
        total_unpriced=11,
        total_shows="unpriced",
    ),
]


@dataclass
class _ExecutionCostProjection:
    cost: ExecutionCost

    async def get_execution_cost(self, execution_id: str) -> ExecutionCost:
        return self.cost


@dataclass
class _Manager:
    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection
    execution_cost: _ExecutionCostProjection


async def _served(monkeypatch: pytest.MonkeyPatch, case: _Coverage) -> ExecutionDetailResponse:
    store = InMemoryProjectionStore()
    detail = WorkflowExecutionDetailProjection(store)
    await detail.on_workflow_execution_started(
        {
            "execution_id": EXECUTION_ID,
            "workflow_id": "wf-897",
            "workflow_name": "priced",
            "started_at": "2026-11-22T10:00:00+00:00",
            "total_phases": 2,
        }
    )
    for phase_id in (PLAN, IMPLEMENT):
        await detail.on_phase_started(
            {
                "execution_id": EXECUTION_ID,
                "phase_id": phase_id,
                "phase_name": phase_id,
                "session_id": f"sess-{phase_id}",
                "started_at": "2026-11-22T10:00:05+00:00",
            }
        )
    cost = ExecutionCost(
        execution_id=EXECUTION_ID,
        workflow_id="wf-897",
        session_count=2,
        session_ids=[f"sess-{PLAN}", f"sess-{IMPLEMENT}"],
        total_cost_usd=case.total,
        token_cost_usd=case.total,
        input_tokens=100,
        output_tokens=200,
        cost_by_phase=case.cost_by_phase,
        unpriced_by_phase=case.unpriced_by_phase,
        unpriced_observation_count=case.total_unpriced,
    )

    from syn_api import _wiring
    from syn_api.routes.executions import queries

    async def _noop_connect() -> None:
        return None

    manager = _Manager(store, detail, _ExecutionCostProjection(cost))
    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)
    response = await queries.get_execution_endpoint(EXECUTION_ID)
    # As a client receives it: through JSON, not the in-process model.
    return ExecutionDetailResponse.model_validate_json(response.model_dump_json())


@pytest.mark.anyio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
async def test_the_execution_total_reads_as_format_cost_renders_it(
    monkeypatch: pytest.MonkeyPatch, case: _Coverage
) -> None:
    body = await _served(monkeypatch, case)

    assert body.total_cost_display == case.total_shows
    assert body.total_cost_display == format_cost(case.total, case.total_unpriced)


@pytest.mark.anyio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
async def test_each_phase_reads_as_its_enriched_cost_not_its_seed(
    monkeypatch: pytest.MonkeyPatch, case: _Coverage
) -> None:
    body = await _served(monkeypatch, case)
    for phase in body.phases:
        assert phase.cost_display == format_cost(phase.cost_usd, phase.unpriced_observation_count)
    assert {p.phase_id: p.cost_display for p in body.phases} == case.phase_shows
