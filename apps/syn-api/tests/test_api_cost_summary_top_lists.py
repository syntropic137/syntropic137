"""GET /costs/summary ranks the models that spent the money.

``top_models`` was built as a ``[]`` literal and never implemented (#701), so
every summary claimed no model had spent anything. It now ranks the same
execution rows the totals are summed from, most expensive first.

``top_sessions`` was left empty by #2225 until sessions could be ranked by cost
in SQL (#2228): ranking ``SessionCostQueryService.list_all()`` in Python loads
every session's token rows and only sees the newest 500 summaries. It now asks
``top_by_cost(TOP_N)`` and never touches the session list; the ranking itself is
pinned against real SQL in ``test_top_sessions_by_cost.py``.

The token half of #701 was fixed by #873; the last test pins it for this route.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost

if TYPE_CHECKING:
    from syn_api.routes.costs import CostSummaryResponse

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


@dataclass
class _FakeSessionCostQuery:
    """Stands in for SessionCostQueryService: already ranked, as its SQL returns them."""

    ranked: list[SessionCost]
    limits: list[int] = field(default_factory=list)

    async def top_by_cost(self, limit: int) -> list[SessionCost]:
        self.limits.append(limit)
        return self.ranked[:limit]

    async def list_all(self, limit: int = 500) -> list[SessionCost]:
        raise AssertionError(
            "the summary must not load the session list: it is unbounded and only"
            " sees the newest 500 summaries (#2228)"
        )


def _ranked_sessions(count: int) -> list[SessionCost]:
    # Distinct costs and token totals per position, so a dropped or reordered
    # entry cannot match by accident.
    return [
        SessionCost(
            session_id=f"sess-{n}",
            total_cost_usd=Decimal(100 - n),
            input_tokens=n,
            cache_read_tokens=1_000 * n,
        )
        for n in range(count)
    ]


async def _summary(
    monkeypatch: pytest.MonkeyPatch,
    executions: list[ExecutionCost],
    sessions: _FakeSessionCostQuery | None = None,
) -> CostSummaryResponse:
    from syn_api.routes import costs

    session_query = sessions or _FakeSessionCostQuery([])
    monkeypatch.setattr(
        costs, "get_execution_cost_query", lambda: _FakeExecutionCostQuery(executions)
    )
    monkeypatch.setattr(costs, "get_session_cost_query", lambda: session_query)
    return await costs.get_cost_summary_endpoint()


@pytest.mark.asyncio
async def test_top_models_sums_each_model_across_executions_most_expensive_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The wire shape, which is what the CLI and dashboard read.
    body = (await _summary(monkeypatch, _executions())).model_dump(mode="json")

    assert body["top_models"] == [
        {"model": OPUS, "cost_usd": "3"},
        {"model": SONNET, "cost_usd": "0.75"},
    ]


@pytest.mark.asyncio
async def test_top_sessions_are_the_ranked_sessions_capped_at_top_n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = _FakeSessionCostQuery(_ranked_sessions(7))

    # The wire shape, which is what the CLI and dashboard read.
    body = (await _summary(monkeypatch, _executions(), sessions)).model_dump(mode="json")

    assert sessions.limits == [5]
    assert body["top_sessions"] == [
        {"session_id": "sess-0", "total_cost_usd": "100", "total_tokens": 0},
        {"session_id": "sess-1", "total_cost_usd": "99", "total_tokens": 1_001},
        {"session_id": "sess-2", "total_cost_usd": "98", "total_tokens": 2_002},
        {"session_id": "sess-3", "total_cost_usd": "97", "total_tokens": 3_003},
        {"session_id": "sess-4", "total_cost_usd": "96", "total_tokens": 4_004},
    ]
    # The route swallows errors into an empty response, so prove it really ran.
    assert body["total_executions"] == 2


@pytest.mark.asyncio
async def test_total_tokens_is_the_sum_of_execution_total_tokens_including_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executions = _executions()

    # The wire shape, which is what the CLI and dashboard read.
    body = (await _summary(monkeypatch, executions)).model_dump(mode="json")

    assert body["total_tokens"] == sum(c.total_tokens for c in executions)
    # Pinned to the literal too: excluding cache tokens would give 132.
    assert body["total_tokens"] == 52_732
