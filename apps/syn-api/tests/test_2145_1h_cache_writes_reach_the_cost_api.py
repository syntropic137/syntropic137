"""The 1-hour cache-write share reaches the cost API (#2145 slice C).

``SessionCost`` and ``ExecutionCost`` have carried ``cache_creation_1h_tokens``
since #2331, and #2333 priced it, but no response exposed it: a client saw the
cache-write total and could not tell how much of it was billed at the 1-hour
rate. These go THROUGH the endpoints with only the cost query stubbed, so both
mapping hops (read model -> DTO -> response) and the rollup stay under test.

1,500 of 4,096 is a share no default could produce, so a dropped hop shows up
as 0 rather than passing by coincidence.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost

pytestmark = pytest.mark.unit


@dataclass
class _StubCostQuery[T]:
    costs: list[T]

    async def list_all(self, limit: int = 500) -> list[T]:
        return self.costs[:limit]


async def _connected() -> None:
    return None


def _stub_costs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sessions: list[SessionCost] | None = None,
    executions: list[ExecutionCost] | None = None,
) -> None:
    from syn_api.routes import costs

    monkeypatch.setattr(costs, "ensure_connected", _connected)
    monkeypatch.setattr(costs, "get_session_cost_query", lambda: _StubCostQuery(sessions or []))
    monkeypatch.setattr(costs, "get_execution_cost_query", lambda: _StubCostQuery(executions or []))


@pytest.mark.asyncio
async def test_a_sessions_1h_writes_reach_the_response(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api.routes.costs import list_session_costs_endpoint

    cost = SessionCost(
        session_id="sess-1", cache_creation_tokens=4096, cache_creation_1h_tokens=1500
    )
    _stub_costs(monkeypatch, sessions=[cost])

    [response] = await list_session_costs_endpoint(execution_id=None, limit=50)

    assert response.cache_creation_tokens == 4096
    assert response.cache_creation_1h_tokens == 1500


@pytest.mark.asyncio
async def test_an_executions_1h_writes_reach_the_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes.costs import list_execution_costs_endpoint

    cost = ExecutionCost(
        execution_id="exec-1", cache_creation_tokens=4096, cache_creation_1h_tokens=1500
    )
    _stub_costs(monkeypatch, executions=[cost])

    [response] = await list_execution_costs_endpoint(limit=50)

    assert response.cache_creation_tokens == 4096
    assert response.cache_creation_1h_tokens == 1500


@pytest.mark.asyncio
async def test_a_row_stored_before_the_field_reports_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row written before #2331 has no 1-hour key; it reads as 0, never fails."""
    from syn_api.routes.costs import list_execution_costs_endpoint, list_session_costs_endpoint

    _stub_costs(
        monkeypatch,
        sessions=[SessionCost.from_dict({"session_id": "sess-old", "cache_creation_tokens": 4096})],
        executions=[
            ExecutionCost.from_dict({"execution_id": "exec-old", "cache_creation_tokens": 4096})
        ],
    )

    [session] = await list_session_costs_endpoint(execution_id=None, limit=50)
    [execution] = await list_execution_costs_endpoint(limit=50)

    assert (session.cache_creation_tokens, session.cache_creation_1h_tokens) == (4096, 0)
    assert (execution.cache_creation_tokens, execution.cache_creation_1h_tokens) == (4096, 0)


@pytest.mark.asyncio
async def test_the_global_cost_sums_the_1h_share(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/insights/cost`` sums ExecutionCost rows; the 1-hour share sums beside the total."""
    from syn_api import _wiring
    from syn_api.routes import insights

    executions = [
        ExecutionCost(execution_id="a", cache_creation_tokens=4096, cache_creation_1h_tokens=1500),
        ExecutionCost(execution_id="b", cache_creation_tokens=1000, cache_creation_1h_tokens=250),
        ExecutionCost(execution_id="c", cache_creation_tokens=700),
    ]
    monkeypatch.setattr(insights, "ensure_connected", _connected)
    monkeypatch.setattr(_wiring, "get_execution_cost_query", lambda: _StubCostQuery(executions))

    response = await insights.get_global_cost_endpoint(system_id=None)

    assert response.total_cache_creation_tokens == 5796
    assert response.total_cache_creation_1h_tokens == 1750
