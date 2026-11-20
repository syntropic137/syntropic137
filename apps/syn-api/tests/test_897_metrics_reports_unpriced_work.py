"""GET /metrics and the workflow runs list say how much work they could not price.

#897 slice H. The dashboard's cost card read ``total_cost_usd`` alone, so work
that carried no usable rate rendered as ``$0.0000`` (free) or as a confident
total (complete) when it was a lower bound. ``/metrics`` now reads its money
and its coverage from the SAME ``ExecutionCost`` rows, through the one rollup
every other cost surface uses, and the runs list passes through the count each
run's execution row already carries.

Driven through the real routes; only the cost query, the canonical totals and
the execution ids are stubbed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.agent_sessions import CanonicalTotals
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

WORKFLOW = "wf-mine"


@dataclass
class _FakeCostQuery:
    """Stands in for ExecutionCostQueryService; records what it was asked."""

    costs: list[ExecutionCost]
    asked_for_ids: list[set[str]] = field(default_factory=list)
    asked_all: int = 0

    async def list_all(self, limit: int = 500) -> list[ExecutionCost]:
        self.asked_all += 1
        return self.costs[:limit]

    async def list_for_ids(self, execution_ids: set[str]) -> list[ExecutionCost]:
        self.asked_for_ids.append(set(execution_ids))
        return [c for c in self.costs if c.execution_id in execution_ids]


class _CanonicalTokens:
    """Tokens stay canonical (#932); its cost is a value no rollup produces."""

    async def totals(self, execution_ids: set[str] | None = None) -> CanonicalTotals:
        return CanonicalTotals(cost_usd=Decimal("999"), input_tokens=7)


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    if hasattr(store, "_state"):
        store._state.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    yield
    reset_storage()
    reset_projection_manager()


def _cost(execution_id: str, usd: str, unpriced: int) -> ExecutionCost:
    return ExecutionCost(
        execution_id=execution_id,
        total_cost_usd=Decimal(usd),
        unpriced_observation_count=unpriced,
    )


async def _metrics(
    monkeypatch: pytest.MonkeyPatch,
    costs: list[ExecutionCost],
    workflow_id: str | None = None,
    workflow_execution_ids: set[str] | None = None,
) -> dict[str, object]:
    from syn_api.routes import metrics

    query = _FakeCostQuery(costs)
    monkeypatch.setattr(metrics, "get_execution_cost_query", lambda: query)
    monkeypatch.setattr(metrics, "get_canonical_usage_query", _CanonicalTokens)

    async def _ids(_workflow_id: str) -> set[str]:
        return workflow_execution_ids or set()

    monkeypatch.setattr(metrics, "_workflow_execution_ids", _ids)
    response = await metrics.get_metrics_endpoint(workflow_id=workflow_id)
    return response.model_dump(mode="json")


class TestGlobalMetrics:
    @pytest.mark.asyncio
    async def test_wholly_unpriced_work_reads_unpriced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = await _metrics(monkeypatch, [_cost("e-1", "0", 4)])

        assert body["total_cost_display"] == "unpriced"
        assert body["unpriced_observation_count"] == 4
        assert body["total_cost_usd"] == "0"

    @pytest.mark.asyncio
    async def test_partly_priced_work_reads_as_a_lower_bound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = await _metrics(monkeypatch, [_cost("e-1", "1.25", 0), _cost("e-2", "0", 2)])

        assert body["total_cost_display"] == ">=$1.25 (partial)"
        assert body["unpriced_observation_count"] == 2
        assert body["total_cost_usd"] == "1.25"

    @pytest.mark.asyncio
    async def test_fully_priced_work_reads_as_a_plain_total(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = await _metrics(monkeypatch, [_cost("e-1", "1.00", 0), _cost("e-2", "0.25", 0)])

        assert body["total_cost_display"] == "$1.25"
        assert body["unpriced_observation_count"] == 0
        assert body["total_cost_usd"] == "1.25"

    @pytest.mark.asyncio
    async def test_two_unpriced_executions_sum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = await _metrics(monkeypatch, [_cost("e-1", "0", 4), _cost("e-2", "0", 9)])

        assert body["unpriced_observation_count"] == 13

    @pytest.mark.asyncio
    async def test_tokens_stay_canonical(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only money moved; tokens still agree with the activity heatmap (#932)."""
        body = await _metrics(monkeypatch, [_cost("e-1", "0.5", 0)])

        assert body["total_input_tokens"] == 7
        assert body["total_cost_usd"] == "0.5"


class TestWorkflowScopedMetrics:
    @pytest.mark.asyncio
    async def test_other_workflows_coverage_and_money_are_excluded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_api.routes import metrics

        costs = [_cost("mine-1", "0.75", 1), _cost("theirs-1", "5", 40)]
        query = _FakeCostQuery(costs)
        monkeypatch.setattr(metrics, "get_execution_cost_query", lambda: query)
        monkeypatch.setattr(metrics, "get_canonical_usage_query", _CanonicalTokens)

        async def _ids(_workflow_id: str) -> set[str]:
            return {"mine-1"}

        monkeypatch.setattr(metrics, "_workflow_execution_ids", _ids)
        body = (await metrics.get_metrics_endpoint(workflow_id=WORKFLOW)).model_dump(mode="json")

        assert body["unpriced_observation_count"] == 1
        assert body["total_cost_usd"] == "0.75"
        assert body["total_cost_display"] == ">=$0.75 (partial)"
        # One read, shared by the totals and the per-phase costs.
        assert query.asked_for_ids == [{"mine-1"}]
        assert query.asked_all == 0

    @pytest.mark.asyncio
    async def test_workflow_with_no_executions_reads_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = await _metrics(monkeypatch, [_cost("theirs-1", "5", 40)], workflow_id=WORKFLOW)

        assert body["unpriced_observation_count"] == 0
        assert body["total_cost_display"] == "$0.00"


@pytest.mark.asyncio
async def test_cost_read_failure_is_503_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    from syn_api.routes import metrics

    class _Down:
        async def list_all(self, limit: int = 500) -> list[ExecutionCost]:
            raise RuntimeError("timescale down")

    monkeypatch.setattr(metrics, "get_execution_cost_query", _Down)
    monkeypatch.setattr(metrics, "get_canonical_usage_query", _CanonicalTokens)

    with pytest.raises(HTTPException) as exc_info:
        await metrics.get_metrics_endpoint(workflow_id=None)
    assert exc_info.value.status_code == 503


# =============================================================================
# GET /workflows/{id}/runs
# =============================================================================


async def _runs_with(
    monkeypatch: pytest.MonkeyPatch, rows: list[tuple[str, str, int]]
) -> list[dict[str, object]]:
    """Each run row is (execution id, total_cost_usd, unpriced count) on its summary."""
    from syn_api.routes.executions import queries as ex_queries
    from syn_api.routes.workflows import queries as wf_queries
    from syn_api.types import ExecutionSummary, Ok, PhaseProgressInfo, WorkflowDetail

    progress = PhaseProgressInfo(
        completed=1, skipped=0, possible=1, remaining_possible=0, percent=100, display="1 of 1"
    )

    async def _resolve(_store: object, _kind: str, workflow_id: str, _label: str) -> str:
        return workflow_id

    async def _get_workflow(workflow_id: str) -> Ok[WorkflowDetail]:
        return Ok(
            WorkflowDetail(
                id=workflow_id, name="Mine", workflow_type="custom", classification="standard"
            )
        )

    async def _list(workflow_id: str | None = None, **_: object) -> Ok[list[ExecutionSummary]]:
        return Ok(
            [
                ExecutionSummary(
                    workflow_execution_id=execution_id,
                    workflow_id=workflow_id or WORKFLOW,
                    workflow_name="Mine",
                    status="completed",
                    phase_progress=progress,
                    repos=[],
                    total_cost_usd=Decimal(usd),
                    unpriced_observation_count=unpriced,
                )
                for execution_id, usd, unpriced in rows
            ]
        )

    monkeypatch.setattr("syn_api.prefix_resolver.resolve_or_raise", _resolve)
    monkeypatch.setattr(wf_queries, "get_workflow", _get_workflow)
    monkeypatch.setattr(ex_queries, "list_", _list)
    response = await wf_queries.list_workflow_runs_endpoint(WORKFLOW)
    return [r.model_dump(mode="json") for r in response.runs]


@pytest.mark.asyncio
async def test_each_run_reports_its_own_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    runs = {
        r["workflow_execution_id"]: r
        for r in await _runs_with(
            monkeypatch,
            [("unpriced", "0", 3), ("partial", "1.25", 2), ("priced", "1.25", 0)],
        )
    }

    assert runs["unpriced"]["total_cost_display"] == "unpriced"
    assert runs["unpriced"]["unpriced_observation_count"] == 3
    assert runs["partial"]["total_cost_display"] == ">=$1.25 (partial)"
    assert runs["partial"]["unpriced_observation_count"] == 2
    assert runs["priced"]["total_cost_display"] == "$1.25"
    assert runs["priced"]["unpriced_observation_count"] == 0
