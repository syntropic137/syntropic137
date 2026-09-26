"""GET /metrics?workflow_id=... reports what each phase cost.

The per-phase ``cost_usd`` was hard-coded to ``Decimal("0")`` beside a comment
promising endpoint enrichment from execution_cost (#695) that never happened.
Live beta.7: every phase read "0" while the same workflow's total read
"0.83128800000000005". Phase cost now comes from the same per-phase source the
execution detail page reads, summed across the workflow's executions, with the
#890 coverage count beside it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal

import pytest
from fastapi import HTTPException

from syn_domain.contexts.agent_sessions import CanonicalTotals
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

WORKFLOW = "multi-agent-programmatic"


class _Boom(Exception):
    pass


@dataclass
class _FakeCostQuery:
    """Stands in for ExecutionCostQueryService; records what it was asked."""

    costs: list[ExecutionCost]
    asked: list[set[str]] = field(default_factory=list)
    fail: bool = False

    async def list_for_ids(self, execution_ids: set[str]) -> list[ExecutionCost]:
        self.asked.append(set(execution_ids))
        if self.fail:
            raise _Boom("timescale down")
        return [c for c in self.costs if c.execution_id in execution_ids]


@dataclass
class _FakeCanonicalQuery:
    async def totals(self, execution_ids: set[str] | None = None) -> CanonicalTotals:
        return CanonicalTotals(cost_usd=Decimal("0.83128800000000005"))


@pytest.fixture(autouse=True)
def _reset_storage():
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


async def _start_phases(*phase_ids: str) -> None:
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    projection = get_projection_mgr().workflow_phase_metrics
    for phase_id in phase_ids:
        await projection.on_phase_started(
            {
                "workflow_id": WORKFLOW,
                "phase_id": phase_id,
                "phase_name": phase_id.title(),
                "started_at": "2026-09-25T00:00:00+00:00",
            }
        )


def _two_executions() -> list[ExecutionCost]:
    # The live noisy doubles, as a SUM over agent_events hands them back.
    return [
        ExecutionCost(
            execution_id="exec-1",
            cost_by_phase={
                "plan": Decimal("0.30566780000000005"),
                "build": Decimal("0.13242320000000001"),
            },
        ),
        ExecutionCost(
            execution_id="exec-2",
            cost_by_phase={"plan": Decimal("0.39319700000000004")},
            unpriced_by_phase={"build": 3},
        ),
    ]


@pytest.mark.asyncio
async def test_phase_cost_is_summed_across_the_workflows_executions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes import metrics

    await _start_phases("plan", "build", "review")
    query = _FakeCostQuery(_two_executions())
    monkeypatch.setattr(metrics, "get_execution_cost_query", lambda: query)

    phases = {
        p.phase_id: p for p in await metrics._build_phase_metrics(WORKFLOW, {"exec-1", "exec-2"})
    }

    assert str(phases["plan"].cost_usd) == "0.6988648"
    assert phases["plan"].unpriced_observation_count == 0
    # Partially priced: a lower bound, and the count says so.
    assert str(phases["build"].cost_usd) == "0.1324232"
    assert phases["build"].unpriced_observation_count == 3
    # Nothing recorded for this phase at all.
    assert phases["review"].cost_usd == Decimal("0")
    assert phases["review"].unpriced_observation_count == 0
    assert query.asked == [{"exec-1", "exec-2"}]


@pytest.mark.asyncio
async def test_phase_cost_read_failure_is_not_reported_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes import metrics

    await _start_phases("plan")
    query = _FakeCostQuery([], fail=True)
    monkeypatch.setattr(metrics, "get_execution_cost_query", lambda: query)

    with pytest.raises(metrics.MetricsUnavailableError, match="unavailable"):
        await metrics._build_phase_metrics(WORKFLOW, {"exec-1"})


@pytest.mark.asyncio
async def test_endpoint_serves_phase_cost_and_reads_execution_ids_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes import metrics

    await _start_phases("plan", "build")
    query = _FakeCostQuery(_two_executions())
    monkeypatch.setattr(metrics, "get_execution_cost_query", lambda: query)
    monkeypatch.setattr(metrics, "get_canonical_usage_query", _FakeCanonicalQuery)

    lookups: list[str] = []

    async def _ids(workflow_id: str) -> set[str]:
        lookups.append(workflow_id)
        return {"exec-1", "exec-2"}

    monkeypatch.setattr(metrics, "_workflow_execution_ids", _ids)

    response = await metrics.get_metrics_endpoint(workflow_id=WORKFLOW)

    body = response.model_dump(mode="json")
    by_id = {p["phase_id"]: p for p in body["phases"]}
    assert by_id["plan"]["cost_usd"] == "0.6988648"
    assert by_id["build"]["cost_usd"] == "0.1324232"
    assert by_id["build"]["unpriced_observation_count"] == 3
    assert lookups == [WORKFLOW]


@pytest.mark.asyncio
async def test_endpoint_returns_503_when_phase_costs_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes import metrics

    await _start_phases("plan")
    monkeypatch.setattr(metrics, "get_execution_cost_query", lambda: _FakeCostQuery([], fail=True))
    monkeypatch.setattr(metrics, "get_canonical_usage_query", _FakeCanonicalQuery)

    async def _ids(workflow_id: str) -> set[str]:
        return {"exec-1"}

    monkeypatch.setattr(metrics, "_workflow_execution_ids", _ids)

    with pytest.raises(HTTPException) as exc_info:
        await metrics.get_metrics_endpoint(workflow_id=WORKFLOW)
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_workflow_without_executions_does_not_query_costs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes import metrics

    await _start_phases("plan")
    query = _FakeCostQuery([], fail=True)
    monkeypatch.setattr(metrics, "get_execution_cost_query", lambda: query)

    phases = await metrics._build_phase_metrics(WORKFLOW, set())

    assert [p.cost_usd for p in phases] == [Decimal("0")]
    assert query.asked == []


@pytest.mark.asyncio
async def test_a_running_phase_marks_its_cost_as_so_far(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A phase still open has no attributed cost for that run yet (#1048).

    ``cost_by_phase`` gains an entry only once a session summary lands, so the
    running run is missing from ``cost_usd``. The flag is what stops a client
    presenting that lower bound as the settled figure.
    """
    from syn_api._wiring import get_projection_mgr
    from syn_api.routes import metrics

    await _start_phases("plan", "build")
    await get_projection_mgr().workflow_phase_metrics.on_phase_completed(
        {
            "workflow_id": WORKFLOW,
            "phase_id": "plan",
            "success": True,
            "duration_seconds": 26.6,
            "completed_at": "2026-09-25T00:00:27+00:00",
        }
    )
    monkeypatch.setattr(
        metrics, "get_execution_cost_query", lambda: _FakeCostQuery(_two_executions())
    )

    phases = {
        p.phase_id: p for p in await metrics._build_phase_metrics(WORKFLOW, {"exec-1", "exec-2"})
    }

    assert phases["plan"].cost_in_progress is False
    assert phases["build"].cost_in_progress is True
