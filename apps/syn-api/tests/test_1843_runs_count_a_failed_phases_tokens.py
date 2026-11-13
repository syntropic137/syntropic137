"""#1843 item 5: a run's tokens on ``/workflows/{id}/runs`` include its failed phases.

THE DEFECT. ``/runs`` read ``total_tokens`` from the domain list row, which adds
a phase's tokens only when the phase COMPLETES, and read the cost from Lane 2,
which counts every phase that reported usage. A failed run therefore showed its
full cost beside the tokens of its completed phases alone, and disagreed with
``/executions/{id}``. Live, exec-75daf295b1a2 read 595,847 tokens on ``/runs``
and 7,190,265 on the detail, with the same $3.701532 on both.

WHY THESE FIXTURES. They are that run's numbers. The list row holds the
completed phase only, exactly as the list projection leaves it, so the failed
phase's 6,594,418 can reach ``/runs`` from Lane 2 and nowhere else.

Both endpoints are called as routes, over the same seeded read models, because
the defect was a constructor one hop before the response, not in either read
model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from syn_api.types import Ok
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostsForIds,
)

if TYPE_CHECKING:
    from syn_api.routes.workflows.queries import ExecutionRunSummary

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

EXEC_ID = "exec-75daf295b1a2"
WORKFLOW_ID = "wf-sdlc-implement-v4-precheck"

# Phase usage, split across components so no single field carries the total.
COMPLETED = {"input_tokens": 1_847, "output_tokens": 94_000, "cache_read_tokens": 500_000}
FAILED = {"input_tokens": 4_418, "output_tokens": 90_000, "cache_read_tokens": 6_500_000}
COMPLETED_TOTAL = 595_847
FAILED_TOTAL = 6_594_418
RUN_TOTAL = 7_190_265
COMPLETED_COST = Decimal("0.412108")
FAILED_COST = Decimal("3.289424")
RUN_COST = Decimal("3.701532")


@dataclass(frozen=True)
class _Workflow:
    name: str


@pytest.fixture(autouse=True)
def _reset_storage():
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    yield
    reset_storage()
    reset_projection_manager()


def _lane2(status: str = "failed") -> ExecutionCost:
    """Lane 2's record of the run: every phase that reported usage."""
    return ExecutionCost(
        execution_id=EXEC_ID,
        workflow_id=WORKFLOW_ID,
        total_cost_usd=RUN_COST,
        token_cost_usd=RUN_COST,
        input_tokens=COMPLETED["input_tokens"] + FAILED["input_tokens"],
        output_tokens=COMPLETED["output_tokens"] + FAILED["output_tokens"],
        cache_read_tokens=COMPLETED["cache_read_tokens"] + FAILED["cache_read_tokens"],
        cost_by_phase={"implement": COMPLETED_COST, "verify": FAILED_COST},
        is_complete=status != "running",
    )


async def _seed(monkeypatch: pytest.MonkeyPatch, status: str = "failed") -> None:
    """One run: a completed phase and a failed one, both of which reported usage."""
    from syn_api import prefix_resolver
    from syn_api._wiring import ensure_connected, get_projection_mgr
    from syn_api.routes.workflows import queries as workflow_queries

    await ensure_connected()
    manager = get_projection_mgr()
    common = {
        "workflow_execution_id": EXEC_ID,
        "workflow_id": WORKFLOW_ID,
        "workflow_name": "sdlc-implement-v4-precheck",
        "status": status,
        "started_at": "2026-11-12T10:00:00Z",
        "completed_at": None if status == "running" else "2026-11-12T11:00:00Z",
        "total_phases": 2,
        "completed_phases": 1,
    }
    # What the list projection holds: tokens are added on PhaseCompleted only.
    await manager.workflow_execution_list._store.save(
        "workflow_executions",
        EXEC_ID,
        {
            **common,
            "total_tokens": COMPLETED_TOTAL,
            "total_input_tokens": COMPLETED["input_tokens"],
            "total_output_tokens": COMPLETED["output_tokens"],
            "total_cache_read_tokens": COMPLETED["cache_read_tokens"],
        },
    )
    await manager.workflow_execution_detail._store.save(
        "workflow_execution_details",
        EXEC_ID,
        {
            **common,
            "execution_id": EXEC_ID,
            "artifact_ids": [],
            "phases": [
                {"workflow_phase_id": "implement", "name": "implement", "status": "completed"}
                | COMPLETED
                | {"total_tokens": COMPLETED_TOTAL},
                {"workflow_phase_id": "verify", "name": "verify", "status": "failed"}
                | FAILED
                | {"total_tokens": FAILED_TOTAL},
            ],
        },
    )
    lane2 = _lane2(status)
    monkeypatch.setattr(
        manager.execution_cost,
        "list_costs_for_ids",
        AsyncMock(return_value=ExecutionCostsForIds(costs=[lane2], tool_calls={})),
    )
    monkeypatch.setattr(manager.execution_cost, "get_execution_cost", AsyncMock(return_value=lane2))

    async def _resolved(_store: object, _table: str, entity_id: str, _label: str) -> str:
        return entity_id

    monkeypatch.setattr(prefix_resolver, "resolve_or_raise", _resolved)
    monkeypatch.setattr(
        workflow_queries,
        "get_workflow",
        AsyncMock(return_value=Ok(_Workflow(name="sdlc-implement-v4-precheck"))),
    )


async def _run_on_runs() -> ExecutionRunSummary:
    from syn_api.routes.workflows.queries import list_workflow_runs_endpoint

    (run,) = (await list_workflow_runs_endpoint(WORKFLOW_ID)).runs
    return run


async def test_runs_and_the_detail_report_the_same_tokens_for_a_failed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes.executions import queries

    await _seed(monkeypatch)

    run = await _run_on_runs()
    detail = await queries.get_execution_endpoint(EXEC_ID)

    assert detail.total_tokens == RUN_TOTAL
    assert run.total_tokens == detail.total_tokens == COMPLETED_TOTAL + FAILED_TOTAL
    assert run.total_tokens != COMPLETED_TOTAL


async def test_tokens_and_cost_count_the_same_phases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cost always counted the failed phase; the tokens beside it must too."""
    from syn_api.routes.executions import queries

    await _seed(monkeypatch)

    run = await _run_on_runs()
    detail = await queries.get_execution_endpoint(EXEC_ID)

    # Cost semantics are unchanged: both phases, on both endpoints.
    assert run.total_cost_usd == detail.total_cost_usd == COMPLETED_COST + FAILED_COST
    # And the tokens are of those same two phases.
    assert run.total_tokens == COMPLETED_TOTAL + FAILED_TOTAL


async def test_the_active_list_reads_the_same_tokens_as_the_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``list_active`` built its summaries by hand with the same split (widened scope)."""
    from syn_api.routes.executions import list_active

    await _seed(monkeypatch, status="running")

    result = await list_active()

    assert isinstance(result, Ok)
    (summary,) = result.value
    assert summary.total_cost_usd == RUN_COST
    assert summary.total_tokens == RUN_TOTAL
