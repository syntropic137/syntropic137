"""/metrics at scale with thousands of summary-less sessions (#2341).

Every session with no priced summary - codex work, a crash, a run still going -
used to be named in the canonical totals statement on every poll, priced group
or not, and thrown away unless its group had no rate. The latency gate's
dataset has 400 such sessions, too few to see it. This one adds 6,000 more,
two in three on rated models and one in three on a model with no rate, each
with two turns that reported tokens and one that reported none (#890).

It holds /metrics, global and scoped, to the latency gate's budgets - never
raised - its coverage and money to the values the seed implies, and its whole
response to what the reader frozen from before #2341 serves for the same
database. Same tier as the gate: `integration`, not run on PRs into main.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx
import pytest

from syn_domain.contexts.agent_sessions import CostCalculator
from syn_shared.events import SESSION_STARTED, TOKEN_USAGE
from syn_shared.pricing import canonical_cost_usd

from .latency_gate import measure, over_budget, report
from .legacy_canonical_totals_pre_2341 import PreBoundCanonicalUsageQueryService
from .test_dashboard_latency_budget import (
    _COLUMNS,
    DAYS,
    ENDPOINTS,
    EXECUTIONS,
    GATED_WORKFLOW,
    _execution,
    _requester,
    _Row,
    _rows,
    _seed_projections,
    _workflow,
    gate_database,  # noqa: F401  # a fixture, used by name
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from .test_dashboard_latency_budget import Endpoint

pytestmark = pytest.mark.integration

SUMMARY_LESS_SESSIONS = 6_000
UNRATED = "mystery-model-1"
MODELS = ("claude-sonnet-5", "claude-haiku-4-5-20251001", UNRATED)
TURN = {"input_tokens": 50, "output_tokens": 5, "cache_read_tokens": 100}
TURN_TOKENS = 155
TURNS_WITH_TOKENS = 2

# The gate's own (base) sessions: a summary on 4 in 5, else 300 turns.
BASE_TURNS = 300
BASE_TURN = (100, 1, 0, 900)
BASE_SUMMARY_TOKENS = 4_000 + 900 + 36_000
BASE_VENDOR_COST = Decimal("0.05")


def _summary_less_rows(now: datetime) -> list[_Row]:
    """Session k runs on MODELS[k % 3] in the gate's execution k % EXECUTIONS."""
    rows: list[_Row] = []
    for k in range(SUMMARY_LESS_SESSIONS):
        session = f"bare-{k}"
        execution = _execution(k % EXECUTIONS)
        model = MODELS[k % 3]
        start = now - timedelta(days=k % DAYS, minutes=k % 600, seconds=30)
        rows.append((start, SESSION_STARTED, session, execution, "p1", "{}"))
        for i in range(TURNS_WITH_TOKENS):
            turn = json.dumps({"model": model, **TURN})
            rows.append(
                (start + timedelta(seconds=1 + i), TOKEN_USAGE, session, execution, "p1", turn)
            )
        zero = json.dumps({"model": model, "input_tokens": 0, "output_tokens": 0})
        rows.append((start + timedelta(seconds=9), TOKEN_USAGE, session, execution, "p1", zero))
    return rows


def _expected(executions: set[str]) -> tuple[int, Decimal, int]:
    """(total tokens, cost, unpriced observations) the seed implies for these executions."""
    tokens = 0
    vendor = Decimal("0")
    by_model: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    unpriced = 0
    for n in range(EXECUTIONS):
        if _execution(n) not in executions:
            continue
        model = ("claude-sonnet-5", "claude-haiku-4-5-20251001")[n % 2]
        if n % 5:
            tokens += BASE_SUMMARY_TOKENS
            vendor += BASE_VENDOR_COST
        else:
            tokens += BASE_TURNS * sum(BASE_TURN)
            for i, value in enumerate(BASE_TURN):
                by_model[model][i] += BASE_TURNS * value
    for k in range(SUMMARY_LESS_SESSIONS):
        if _execution(k % EXECUTIONS) not in executions:
            continue
        model = MODELS[k % 3]
        tokens += TURNS_WITH_TOKENS * TURN_TOKENS
        if model == UNRATED:
            unpriced += TURNS_WITH_TOKENS
            continue
        by_model[model][0] += TURNS_WITH_TOKENS * TURN["input_tokens"]
        by_model[model][1] += TURNS_WITH_TOKENS * TURN["output_tokens"]
        by_model[model][3] += TURNS_WITH_TOKENS * TURN["cache_read_tokens"]
    calculator = CostCalculator()
    cost = vendor
    for model, (inp, out, creation, read) in by_model.items():
        pricing = calculator.resolve_pricing(model)
        assert pricing is not None, model
        cost += pricing.calculate_cost(inp, out, creation, read)
    return tokens, canonical_cost_usd(cost), unpriced


@pytest.fixture
async def app_with_summary_less_sessions(
    gate_database: str,  # noqa: F811  # the imported fixture, requested by name
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    """The gate's app and dataset, plus the summary-less sessions."""
    from syn_adapters import projection_stores
    from syn_adapters.events import AgentEventStore, store_helpers
    from syn_adapters.projection_stores import PostgresProjectionStore
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_api.main import create_app

    store = AgentEventStore(gate_database)
    await store.initialize()
    pool = store.pool
    assert pool is not None
    monkeypatch.setattr(store_helpers, "_event_store", store)
    monkeypatch.setattr(projection_stores, "_store_instance", PostgresProjectionStore(pool))
    reset_projection_manager()

    async with pool.acquire() as conn:
        now = datetime.now(UTC).replace(microsecond=0)
        records = _rows(now) + _summary_less_rows(now)
        await conn.copy_records_to_table("agent_events", records=records, columns=_COLUMNS)
    await _seed_projections()
    async with pool.acquire() as conn:
        await conn.execute("ANALYZE")

    try:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        reset_projection_manager()
        await store.close()


async def _served_before_2341(
    client: httpx.AsyncClient, endpoint: Endpoint, monkeypatch: pytest.MonkeyPatch
) -> object:
    """The whole /metrics body, with the totals read as they were before #2341."""
    from syn_api import _wiring
    from syn_api.routes import metrics as metrics_route
    from syn_domain.contexts.agent_sessions import CostCalculator

    with monkeypatch.context() as patch:
        patch.setattr(
            metrics_route,
            "get_canonical_usage_query",
            lambda: PreBoundCanonicalUsageQueryService(
                pool=_wiring._timescale_pool(), cost_calculator=CostCalculator()
            ),
        )
        return (await client.get(endpoint.path, params=endpoint.params)).json()


async def test_metrics_holds_its_budget_and_its_numbers_with_summary_less_sessions(
    app_with_summary_less_sessions: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = app_with_summary_less_sessions
    every_execution = {_execution(n) for n in range(EXECUTIONS)}
    gated = {_execution(n) for n in range(EXECUTIONS) if _workflow(n) == GATED_WORKFLOW}
    metrics = [e for e in ENDPOINTS if e.path == "/metrics"]

    for endpoint, executions in zip(metrics, (every_execution, gated), strict=True):
        body = (await client.get(endpoint.path, params=endpoint.params)).json()
        before = await _served_before_2341(client, endpoint, monkeypatch)
        assert body == before, (endpoint.name, body, before)
        tokens, cost, unpriced = _expected(executions)
        assert unpriced > 0, endpoint.name  # the scope holds unpriced work to count
        assert body["unpriced_observation_count"] == unpriced, (endpoint.name, body)
        assert body["total_tokens"] == tokens, (endpoint.name, body)
        assert Decimal(str(body["total_cost_usd"])) == cost, (endpoint.name, body)

    measured = await measure(_requester(client), metrics)
    table = report(
        f"/metrics with {SUMMARY_LESS_SESSIONS} summary-less sessions", metrics, measured
    )
    with capsys.disabled():  # the numbers belong in the CI log, pass or fail
        print(f"\n{table}")
    over = over_budget(metrics, measured)
    assert not over, f"p95 over budget for {over}:\n{table}"
