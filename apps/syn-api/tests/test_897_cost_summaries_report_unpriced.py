"""Both cost summaries say how much work they could not price (#897 slice E).

``GET /costs/summary`` and ``GET /events/sessions/{id}/costs`` returned a dollar
figure with no coverage, so a summary of wholly unpriced codex runs read as
``$0`` - indistinguishable from free work (#890). Each now carries
``unpriced_observation_count`` from the SAME rows its money is summed from, and
a ``total_cost_display`` that says ``unpriced`` or ``>=$X (partial)`` when the
figure is incomplete.

Driven through the real routes with only the query or projection stubbed, and
asserted on the wire shape the CLI and dashboard read.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost

if TYPE_CHECKING:
    from syn_api.routes.costs import CostSummaryResponse
    from syn_api.routes.events import CostSummaryResponse as SessionCostSummaryResponse

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")


@dataclass
class _FakeExecutionCostQuery:
    costs: list[ExecutionCost]

    async def list_all(self, limit: int = 500) -> list[ExecutionCost]:
        return self.costs[:limit]


@dataclass
class _FakeSessionCostQuery:
    async def top_by_cost(self, limit: int) -> list[SessionCost]:
        return []


def _execution(execution_id: str, cost: str, unpriced: int) -> ExecutionCost:
    return ExecutionCost(
        execution_id=execution_id,
        total_cost_usd=Decimal(cost),
        unpriced_observation_count=unpriced,
    )


async def _cost_summary(
    monkeypatch: pytest.MonkeyPatch, executions: list[ExecutionCost]
) -> CostSummaryResponse:
    from syn_api.routes import costs

    async def _connected() -> None:
        return None

    monkeypatch.setattr(costs, "ensure_connected", _connected)
    monkeypatch.setattr(
        costs, "get_execution_cost_query", lambda: _FakeExecutionCostQuery(executions)
    )
    monkeypatch.setattr(costs, "get_session_cost_query", _FakeSessionCostQuery)
    response = await costs.get_cost_summary_endpoint()
    # The route swallows errors into an empty response, so prove it really ran.
    assert response.total_executions == len(executions)
    return response


@pytest.mark.asyncio
async def test_cost_summary_of_wholly_unpriced_work_says_unpriced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _cost_summary(monkeypatch, [_execution("exec-1", "0", 4)])
    # The wire shape, which is what the CLI and dashboard read.
    body = response.model_dump(mode="json")

    assert body["unpriced_observation_count"] == 4
    assert body["total_cost_display"] == "unpriced"


@pytest.mark.asyncio
async def test_cost_summary_of_partly_priced_work_is_a_lower_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _cost_summary(
        monkeypatch, [_execution("exec-1", "1.25", 0), _execution("exec-2", "0", 2)]
    )
    # The wire shape, which is what the CLI and dashboard read.
    body = response.model_dump(mode="json")

    assert body["unpriced_observation_count"] == 2
    assert body["total_cost_display"] == ">=$1.25 (partial)"


@pytest.mark.asyncio
async def test_cost_summary_of_fully_priced_work_is_a_plain_dollar_figure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _cost_summary(
        monkeypatch, [_execution("exec-1", "1.25", 0), _execution("exec-2", "2.50", 0)]
    )
    # The wire shape, which is what the CLI and dashboard read.
    body = response.model_dump(mode="json")

    assert body["unpriced_observation_count"] == 0
    assert body["total_cost_display"] == "$3.75"
    assert body["total_cost_usd"] == "3.75"


@pytest.mark.asyncio
async def test_cost_summary_sums_unpriced_counts_across_executions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _cost_summary(
        monkeypatch, [_execution("exec-1", "0", 2), _execution("exec-2", "0", 3)]
    )
    # The wire shape, which is what the CLI and dashboard read.
    body = response.model_dump(mode="json")

    assert body["unpriced_observation_count"] == 5
    assert body["total_cost_display"] == "unpriced"


@dataclass
class _FakeSessionCostProjection:
    cost: SessionCost

    async def get_session_cost(self, session_id: str) -> SessionCost | None:
        return self.cost if session_id == self.cost.session_id else None


@dataclass
class _FakeManager:
    session_cost: _FakeSessionCostProjection
    store: object = None


async def _session_costs(
    monkeypatch: pytest.MonkeyPatch, cost: SessionCost
) -> SessionCostSummaryResponse:
    from syn_api import prefix_resolver
    from syn_api.routes import events

    async def _connected() -> None:
        return None

    async def _resolve(_store: object, _ns: str, partial_id: str, _entity: str) -> str:
        return partial_id

    manager = _FakeManager(_FakeSessionCostProjection(cost))
    monkeypatch.setattr(events, "ensure_connected", _connected)
    monkeypatch.setattr(events, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(prefix_resolver, "resolve_or_raise", _resolve)
    return await events.get_session_costs_endpoint(cost.session_id)


@pytest.mark.asyncio
async def test_session_costs_of_wholly_unpriced_work_say_unpriced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _session_costs(
        monkeypatch, SessionCost(session_id="sess-1", unpriced_observation_count=3)
    )
    # The wire shape, which is what the CLI and dashboard read.
    body = response.model_dump(mode="json")

    assert body["unpriced_observation_count"] == 3
    assert body["total_cost_display"] == "unpriced"


@pytest.mark.asyncio
async def test_session_costs_of_partly_priced_work_are_a_lower_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _session_costs(
        monkeypatch,
        SessionCost(
            session_id="sess-1", total_cost_usd=Decimal("0.42"), unpriced_observation_count=1
        ),
    )
    # The wire shape, which is what the CLI and dashboard read.
    body = response.model_dump(mode="json")

    assert body["unpriced_observation_count"] == 1
    assert body["total_cost_display"] == ">=$0.42 (partial)"
    assert body["estimated_cost_usd"] == "0.42"


@pytest.mark.asyncio
async def test_session_costs_of_fully_priced_work_are_a_plain_dollar_figure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _session_costs(
        monkeypatch,
        SessionCost(session_id="sess-1", total_cost_usd=Decimal("0.42"), input_tokens=7),
    )
    # The wire shape, which is what the CLI and dashboard read.
    body = response.model_dump(mode="json")

    assert body["unpriced_observation_count"] == 0
    assert body["total_cost_display"] == "$0.42"
    assert body["input_tokens"] == 7
