"""GET /costs/summary ranks the models and sessions that spent the money.

``top_models`` and ``top_sessions`` were built as ``[]`` literals and never
implemented (#701), so every summary claimed nothing had been spent by anyone.
They now rank the same rows the totals are summed from, most expensive first.

The token half of #701 was fixed by #873; the last test pins it for this route.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

OPUS = "claude-opus-4-1-20250805"
SONNET = "claude-sonnet-4-5-20250929"


@dataclass
class _FakeExecutionCostQuery:
    """Stands in for ExecutionCostQueryService."""

    costs: list[ExecutionCost]

    async def list_all(self, limit: int = 500) -> list[ExecutionCost]:
        return self.costs[:limit]


@dataclass
class _FakeSessionCostQuery:
    """Stands in for SessionCostQueryService."""

    costs: list[SessionCost]

    async def list_all(self, limit: int = 500) -> list[SessionCost]:
        return self.costs[:limit]


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


def _executions() -> list[ExecutionCost]:
    # Sonnet is listed first everywhere so insertion order is NOT cost order.
    return [
        ExecutionCost(
            execution_id="exec-1",
            session_count=2,
            total_cost_usd=Decimal("1.50"),
            input_tokens=100,
            output_tokens=20,
            cache_creation_tokens=3_000,
            cache_read_tokens=40_000,
            tool_calls=4,
            cost_by_model={SONNET: Decimal("0.50"), OPUS: Decimal("1.00")},
        ),
        ExecutionCost(
            execution_id="exec-2",
            session_count=1,
            total_cost_usd=Decimal("2.25"),
            input_tokens=7,
            output_tokens=5,
            cache_creation_tokens=600,
            cache_read_tokens=9_000,
            tool_calls=1,
            cost_by_model={SONNET: Decimal("0.25"), OPUS: Decimal("2.00")},
        ),
    ]


def _sessions(n: int) -> list[SessionCost]:
    # Cheapest first, so a passing order cannot be the input order.
    return [
        SessionCost(
            session_id=f"sess-{i}",
            total_cost_usd=Decimal(i) / Decimal(10),
            input_tokens=i,
            cache_read_tokens=1_000 * i,
        )
        for i in range(1, n + 1)
    ]


async def _summary(
    monkeypatch: pytest.MonkeyPatch,
    executions: list[ExecutionCost],
    sessions: list[SessionCost],
) -> dict[str, object]:
    from syn_api.routes import costs

    monkeypatch.setattr(costs, "get_execution_cost_query", lambda: _FakeExecutionCostQuery(executions))
    monkeypatch.setattr(costs, "get_session_cost_query", lambda: _FakeSessionCostQuery(sessions))
    response = await costs.get_cost_summary_endpoint()
    # The wire shape, which is what the CLI and dashboard read.
    return response.model_dump(mode="json")


@pytest.mark.asyncio
async def test_top_models_sums_each_model_across_executions_most_expensive_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = await _summary(monkeypatch, _executions(), _sessions(1))

    assert body["top_models"] == [
        {"model": OPUS, "cost_usd": "3"},
        {"model": SONNET, "cost_usd": "0.75"},
    ]


@pytest.mark.asyncio
async def test_top_sessions_are_most_expensive_first_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes.costs import TOP_N

    body = await _summary(monkeypatch, _executions(), _sessions(TOP_N + 2))

    top = body["top_sessions"]
    assert isinstance(top, list)
    assert [s["session_id"] for s in top] == [f"sess-{i}" for i in range(TOP_N + 2, 2, -1)]
    assert top[0] == {
        "session_id": f"sess-{TOP_N + 2}",
        "total_cost_usd": str(Decimal(TOP_N + 2) / Decimal(10)),
        "total_tokens": (TOP_N + 2) * 1_001,
    }


@pytest.mark.asyncio
async def test_total_tokens_is_the_sum_of_execution_total_tokens_including_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executions = _executions()

    body = await _summary(monkeypatch, executions, [])

    assert body["total_tokens"] == sum(c.total_tokens for c in executions)
    # Pinned to the literal too: excluding cache tokens would give 132.
    assert body["total_tokens"] == 52_732
