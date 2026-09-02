"""`GET /api/v1/executions` must load Lane 2 cost enrichment once per row, not twice.

Issue #1069: the endpoint was measured at a ~2.4s floor 45x slower than sibling
endpoints, independent of page size. `list_executions_endpoint` called
`list_()` (which already runs the per-row `execution_cost.get_execution_cost`
loop internally to populate `total_cost_usd`) and then called the *same*
per-row loop again, independently, to get the token breakdown needed for
`_merge_totals`. Neither result was cached or threaded through, so every
request against N executions issued 2N (or, against TimescaleDB, 10-12N -
`get_execution_cost` runs five or six aggregate SQL statements per call) round
trips instead of N.

This test proves the loop runs once by counting calls on the stubbed
`execution_cost` projection - the thing the fix must reduce - not by
inspecting the response body, which is identical whether the loop runs once
or twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api.routes.executions.queries import list_executions_endpoint

pytestmark = pytest.mark.unit

EXECUTION_IDS = ["exec-0", "exec-1", "exec-2", "exec-3", "exec-4"]


@dataclass
class _DomainSummary:
    workflow_execution_id: str
    workflow_id: str = "wf-1069"
    workflow_name: str = "Workflow"
    status: str = "running"
    started_at: str | None = None
    completed_at: str | None = None
    completed_phases: int = 0
    total_phases: int = 1
    total_tokens: int = 100
    total_input_tokens: int = 50
    total_output_tokens: int = 50
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    error_message: str | None = None
    repos: list[str] = field(default_factory=list)


@dataclass
class _ExecutionCost:
    total_cost_usd: Decimal = Decimal("0.01")
    unpriced_observation_count: int = 0
    input_tokens: int = 50
    output_tokens: int = 50
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


async def _call() -> tuple[list, list[str]]:
    """Invoke the endpoint with the projection layer faked out.

    Returns the response's executions and the list of execution_ids the
    stubbed `get_execution_cost` was actually called with, in call order.
    """
    summaries = [_DomainSummary(workflow_execution_id=eid) for eid in EXECUTION_IDS]
    calls: list[str] = []

    async def fake_get_execution_cost(execution_id: str) -> _ExecutionCost:
        calls.append(execution_id)
        return _ExecutionCost()

    mgr = MagicMock()
    mgr.workflow_execution_list.get_all = AsyncMock(return_value=summaries)
    mgr.execution_cost.get_execution_cost = AsyncMock(side_effect=fake_get_execution_cost)

    with (
        patch(
            "syn_api.routes.executions.queries.ensure_connected",
            new=AsyncMock(),
        ),
        patch(
            "syn_api.routes.executions.queries.get_projection_mgr",
            return_value=mgr,
        ),
    ):
        resp = await list_executions_endpoint(status=None, page=1, page_size=50)

    return resp.executions, calls


async def test_get_execution_cost_is_called_once_per_row_not_twice() -> None:
    """The regression: 2N calls for N rows, doubling every SQL round trip."""
    _executions, calls = await _call()

    assert calls == EXECUTION_IDS, (
        f"expected exactly one get_execution_cost call per execution_id "
        f"({EXECUTION_IDS}), got {calls} - the enrichment loop ran more than "
        "once over the same page (#1069)"
    )


async def test_response_still_carries_the_enriched_totals() -> None:
    """De-duplicating the loop must not silently drop the values it fed."""
    executions, _calls = await _call()

    assert len(executions) == len(EXECUTION_IDS)
    for execution in executions:
        assert execution.total_cost_usd == Decimal("0.01")
        assert execution.total_input_tokens == 50
        assert execution.total_output_tokens == 50
