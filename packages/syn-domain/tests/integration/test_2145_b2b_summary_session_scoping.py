"""Summary totals and their cache TTL split must cover the same sessions.

Execute all three execution turn queries against the real store, with two
sessions on the SAME model. Model grouping alone must not merge their TTLs.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.events import AgentEventStore
from syn_domain.contexts.agent_sessions.slices.session_cost.query_service import (
    SessionCostQueryService,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    TimescaleSessionCostQuery,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostQueryService,
)
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    TimescaleExecutionCostQuery,
)
from syn_shared.agents import ModelId

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_tests.fixtures.infrastructure import TestInfrastructure

    from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
_MILLION = 1_000_000


@pytest.fixture
async def event_store(test_infrastructure: TestInfrastructure) -> AsyncIterator[AgentEventStore]:
    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    try:
        yield store
    finally:
        await store.close()


async def _read(store: AgentEventStore, execution_id: str, reader: str) -> ExecutionCost:
    if reader == "detail":
        cost = await TimescaleExecutionCostQuery(store.pool).calculate(execution_id)
        assert cost is not None
        return cost
    query = ExecutionCostQueryService(store.pool)
    costs = await query.list_all() if reader == "list" else await query.list_for_ids([execution_id])
    return next(cost for cost in costs if cost.execution_id == execution_id)


@pytest.mark.parametrize("reader", ["list", "by_ids", "detail"])
@pytest.mark.parametrize("reported", [True, False])
async def test_summary_split_tracks_only_the_sessions_in_its_total(
    event_store: AgentEventStore, reader: str, reported: bool
) -> None:
    execution_id = f"exec-{uuid4()}"
    finished, running = f"sess-{uuid4()}", f"sess-{uuid4()}"
    collectors = {
        session_id: ObservabilityCollector(
            event_store, session_id, execution_id, "phase-1", None, "opus"
        )
        for session_id in (finished, running)
    }
    for session_id, one_hour in ((finished, 0), (running, _MILLION)):
        collector = collectors[session_id]
        collector.note_observed_model(ModelId.CLAUDE_OPUS_5_5.value)
        await collector.record_token_usage(0, 0, _MILLION, 0, cache_creation_1h=one_hour)

    # No summaries: both sessions still contribute, including the 1-hour writes.
    before = await _read(event_store, execution_id, reader)
    assert before.cache_creation_tokens == 2 * _MILLION
    assert before.cache_creation_1h_tokens == _MILLION
    assert before.total_cost_usd == Decimal("13.00")

    await collectors[finished].record_session_summary(
        5.0 if reported else None, 0, 0, _MILLION, 0, 1, 0
    )
    partial = await _read(event_store, execution_id, reader)
    assert partial.session_ids == [finished]
    assert partial.cache_creation_tokens == _MILLION
    assert partial.cache_creation_1h_tokens == 0
    assert partial.total_cost_usd == Decimal("5.00")

    # Both session readers must keep the unfinished session's TTL out of its neighbour.
    sessions = await TimescaleSessionCostQuery(event_store.pool).calculate_many([finished, running])
    listed = await SessionCostQueryService(event_store.pool).list_all()
    for session_id, one_hour, dollars in ((finished, 0, "5.00"), (running, _MILLION, "8.00")):
        for session in (
            sessions[session_id],
            next(s for s in listed if s.session_id == session_id),
        ):
            assert session.cache_creation_tokens == _MILLION
            assert session.cache_creation_1h_tokens == one_hour
            assert session.total_cost_usd == Decimal(dollars)

    # The second completion changes membership: its 1-hour share must now count.
    await collectors[running].record_session_summary(
        8.0 if reported else None, 0, 0, _MILLION, 0, 1, 0
    )
    complete = await _read(event_store, execution_id, reader)
    assert set(complete.session_ids) == {finished, running}
    assert complete.cache_creation_tokens == before.cache_creation_tokens
    assert complete.cache_creation_1h_tokens == before.cache_creation_1h_tokens
    assert complete.total_cost_usd == before.total_cost_usd
