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
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost

if TYPE_CHECKING:
    from syn_api.routes.events import CostSummaryResponse as SessionCostSummaryResponse

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


@dataclass
class _StubSessionCostProjection:
    cost: SessionCost

    async def get_session_cost(self, session_id: str) -> SessionCost | None:
        return self.cost if session_id == self.cost.session_id else None


@dataclass
class _StubManager:
    session_cost: _StubSessionCostProjection
    store: object = None


async def _events_session_costs(
    monkeypatch: pytest.MonkeyPatch, cost: SessionCost
) -> SessionCostSummaryResponse:
    """``GET /events/sessions/{id}/costs``, the route ``syn events costs`` reads."""
    from syn_api import prefix_resolver
    from syn_api.routes import events

    async def _resolve(_store: object, _ns: str, partial_id: str, _entity: str) -> str:
        return partial_id

    manager = _StubManager(_StubSessionCostProjection(cost))
    monkeypatch.setattr(events, "ensure_connected", _connected)
    monkeypatch.setattr(events, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(prefix_resolver, "resolve_or_raise", _resolve)
    return await events.get_session_costs_endpoint(cost.session_id)


@pytest.mark.asyncio
async def test_the_events_session_cost_carries_the_1h_share(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The events route has its own ``CostSummaryResponse``, built via ``TokenMetrics``."""
    response = await _events_session_costs(
        monkeypatch,
        SessionCost(session_id="sess-1", cache_creation_tokens=4096, cache_creation_1h_tokens=1500),
    )
    # The wire shape, which is what the CLI and dashboard read.
    body = response.model_dump(mode="json")

    assert body["cache_creation_tokens"] == 4096
    assert body["cache_creation_1h_tokens"] == 1500


@pytest.mark.asyncio
async def test_the_events_session_cost_of_an_older_row_reports_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _events_session_costs(
        monkeypatch,
        SessionCost.from_dict({"session_id": "sess-old", "cache_creation_tokens": 4096}),
    )
    body = response.model_dump(mode="json")

    assert body["cache_creation_tokens"] == 4096
    assert body["cache_creation_1h_tokens"] == 0
