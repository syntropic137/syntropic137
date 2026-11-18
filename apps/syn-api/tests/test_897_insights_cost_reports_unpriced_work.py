"""The insights cost surface says how much work it could not price (issue #897).

``ExecutionCost`` has carried ``unpriced_observation_count`` since #788, and #898
carried it through the session and execution surfaces. ``/insights/cost`` summed
``total_cost_usd`` across executions and dropped the count, so a fleet whose
codex runs had no rate rendered as a confident ``$0.00`` (#890).

These go THROUGH the endpoint with only the cost query stubbed, so
``_aggregate_costs`` and the response construction both stay under test. The
rendered ``total_cost_display`` is asserted, not just the count: carrying the
number and still printing ``$X.XX`` beside it is the failure this guards.

Repo-scoped cost (``/repos/{id}/cost``) is not here: it reads the ``RepoCost``
read model, which has no unpriced count to carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost

PRICED_MODEL = "claude-sonnet-4-5"


def _unpriced_execution() -> ExecutionCost:
    """A codex run whose model has no rate: real tokens, no dollars."""
    return ExecutionCost(
        execution_id="exec-unpriced",
        workflow_id="wf-codex",
        input_tokens=40,
        output_tokens=1_700,
        total_cost_usd=Decimal("0"),
        unpriced_observation_count=9,
    )


def _priced_execution() -> ExecutionCost:
    return ExecutionCost(
        execution_id="exec-priced",
        workflow_id="wf-claude",
        input_tokens=100,
        output_tokens=200,
        total_cost_usd=Decimal("1.25"),
        cost_by_model={PRICED_MODEL: Decimal("1.25")},
    )


@dataclass
class _StubExecutionCostQuery:
    """Stands in for ``ExecutionCostQueryService`` at the ``get_global_cost`` seam."""

    costs: list[ExecutionCost]

    async def list_all(self, limit: int = 500) -> list[ExecutionCost]:
        return self.costs[:limit]


@dataclass
class _StubProjectionStore:
    async def get(self, projection: str, key: str) -> dict[str, str] | None:
        return {"name": "Payments"}


def _patch(monkeypatch: pytest.MonkeyPatch, costs: list[ExecutionCost]) -> None:
    import syn_adapters.projection_stores as projection_stores
    from syn_api import _wiring
    from syn_api.routes import insights

    async def _connected() -> None:
        return None

    async def _all_ids(system_id: str) -> set[str]:
        return {c.execution_id for c in costs}

    monkeypatch.setattr(insights, "ensure_connected", _connected)
    monkeypatch.setattr(_wiring, "get_execution_cost_query", lambda: _StubExecutionCostQuery(costs))
    monkeypatch.setattr(insights, "_get_execution_ids_for_system", _all_ids)
    monkeypatch.setattr(projection_stores, "get_projection_store", lambda: _StubProjectionStore())


@pytest.mark.unit
class TestInsightsCostReportsUnpricedWork:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("system_id", [None, "sys-1"], ids=["global", "system"])
    async def test_a_partly_unpriced_fleet_is_a_lower_bound(
        self, monkeypatch: pytest.MonkeyPatch, system_id: str | None
    ) -> None:
        from syn_api.routes.insights import get_global_cost_endpoint

        _patch(monkeypatch, [_unpriced_execution(), _priced_execution()])

        response = await get_global_cost_endpoint(system_id=system_id)

        assert response.unpriced_observation_count == 9
        assert response.total_cost_usd == "1.25"
        assert response.total_cost_display == ">=$1.25 (partial)"

    @pytest.mark.asyncio
    async def test_a_wholly_unpriced_fleet_is_unpriced_not_zero_dollars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_api.routes.insights import get_global_cost_endpoint

        _patch(monkeypatch, [_unpriced_execution()])

        response = await get_global_cost_endpoint(system_id=None)

        assert response.unpriced_observation_count == 9
        assert response.total_cost_display == "unpriced"

    @pytest.mark.asyncio
    async def test_a_fully_priced_fleet_renders_as_a_plain_total(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_api.routes.insights import get_global_cost_endpoint

        _patch(monkeypatch, [_priced_execution()])

        response = await get_global_cost_endpoint(system_id=None)

        assert response.unpriced_observation_count == 0
        assert response.total_cost_display == "$1.25"

    @pytest.mark.asyncio
    async def test_the_workflow_breakdown_names_the_unpriced_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_api.routes.insights import get_global_cost_endpoint

        _patch(monkeypatch, [_unpriced_execution(), _priced_execution()])

        response = await get_global_cost_endpoint(system_id=None)

        assert response.unpriced_by_workflow == {"wf-codex": 9}
        assert response.cost_by_workflow == {"wf-codex": "0", "wf-claude": "1.25"}
