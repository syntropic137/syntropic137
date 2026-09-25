"""Legacy and ADR-067 rows attribute identically through real SQL and replay.

The unit suite feeds the SQL row mappers hand-built rows, so it cannot see
whether the queries actually project ``requested_model`` and
``data ? 'requested_model'`` - or group on them. That is a property of the SQL,
so it is pinned here against a real database: the same mixed rows are written
through the real store, read back through the real queries, and compared with
what the in-memory projections make of the same observations.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from syn_domain.contexts.agent_sessions import (
    CanonicalUsageQueryService,
    CostCalculator,
    TokenUsageData,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import (
    SessionCostProjection,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    TimescaleSessionCostQuery,
)
from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
    ExecutionCostProjection,
)
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    TimescaleExecutionCostQuery,
)
from syn_shared.agents import ModelAlias, ModelId
from syn_shared.events import SESSION_SUMMARY, TOKEN_USAGE
from syn_shared.observed_model import UNKNOWN_MODEL_KEY

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

ALIAS = ModelAlias.OPUS
REPORTED = ModelId.CLAUDE_OPUS_5_5
OTHER_REPORTED = ModelId.CLAUDE_SONNET_5


def _row(tokens: int, model: str | None, *, requested: bool) -> TokenUsageData:
    """A token_usage payload: ADR-067-era when ``requested``, legacy otherwise."""
    row = TokenUsageData(
        input_tokens=tokens,
        output_tokens=tokens // 10,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        model=model,
    )
    if requested:
        row["requested_model"] = ALIAS
    return row


MIXED: tuple[TokenUsageData, ...] = (
    _row(1000, ALIAS, requested=False),  # legacy: the alias was the request
    _row(700, REPORTED, requested=False),  # legacy: an explicit id
    _row(300, REPORTED, requested=True),
    _row(200, OTHER_REPORTED, requested=True),
    _row(500, None, requested=True),
)


class _Store[RowT]:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], RowT] = {}

    async def save(self, name: str, key: str, value: RowT) -> None:
        self._rows[(name, key)] = value

    async def get(self, name: str, key: str) -> RowT | None:
        return self._rows.get((name, key))


@pytest.fixture
async def event_store(test_infrastructure):
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    yield store
    await store.close()


async def _write(event_store, session_id: str, execution_id: str) -> None:
    for data in MIXED:
        await event_store.record_observation(
            session_id=session_id,
            observation_type=TOKEN_USAGE,
            data=dict(data),
            execution_id=execution_id,
            phase_id="phase-1",
        )


async def _replay(projection, session_id: str, execution_id: str) -> None:
    for data in MIXED:
        await projection.on_agent_observation(
            {
                "session_id": session_id,
                "execution_id": execution_id,
                "phase_id": "phase-1",
                "event_type": TOKEN_USAGE,
                "data": data,
            }
        )


async def test_session_cost_agrees_with_replay(event_store) -> None:
    session_id = f"sess-{uuid4()}"
    execution_id = f"exec-{uuid4()}"
    await _write(event_store, session_id, execution_id)

    projection = SessionCostProjection(store=_Store())  # type: ignore[arg-type]
    await _replay(projection, session_id, execution_id)
    replayed = await projection.get_session_cost(session_id)
    assert replayed is not None

    queried = await TimescaleSessionCostQuery(event_store.pool).calculate(session_id)
    assert queried is not None

    assert queried.cost_by_model == replayed.cost_by_model
    assert queried.total_cost_usd == replayed.total_cost_usd
    assert queried.agent_model == replayed.agent_model
    assert queried.requested_model == replayed.requested_model
    assert ALIAS not in queried.cost_by_model
    assert UNKNOWN_MODEL_KEY in queried.cost_by_model
    assert queried.agent_model in {REPORTED, OTHER_REPORTED}


async def test_execution_cost_agrees_with_replay(event_store) -> None:
    execution_id = f"exec-{uuid4()}"
    session_id = f"sess-{uuid4()}"
    await _write(event_store, session_id, execution_id)

    projection = ExecutionCostProjection(store=_Store())  # type: ignore[arg-type]
    await _replay(projection, session_id, execution_id)
    replayed = await projection.get_execution_cost(execution_id)
    assert replayed is not None

    queried = await TimescaleExecutionCostQuery(event_store.pool).calculate(execution_id)
    assert queried is not None

    assert queried.cost_by_model == replayed.cost_by_model
    assert queried.total_cost_usd == replayed.total_cost_usd


async def test_canonical_totals_price_legacy_rows_as_before(event_store) -> None:
    """The alias row still costs what it always cost; only its label moved."""
    execution_id = f"exec-{uuid4()}"
    await _write(event_store, f"sess-{uuid4()}", execution_id)

    totals = await CanonicalUsageQueryService(event_store.pool, CostCalculator()).totals(
        {execution_id}
    )
    queried = await TimescaleExecutionCostQuery(event_store.pool).calculate(execution_id)
    assert queried is not None
    assert totals.cost_usd == queried.total_cost_usd
    assert totals.unpriced_tokens == 0


async def test_a_legacy_alias_summary_reports_no_model_that_ran(event_store) -> None:
    session_id = f"sess-{uuid4()}"
    await event_store.record_observation(
        session_id=session_id,
        observation_type=SESSION_SUMMARY,
        data={
            "total_input_tokens": 1000,
            "total_output_tokens": 100,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "model": ALIAS,
        },
    )

    queried = await TimescaleSessionCostQuery(event_store.pool).calculate(session_id)
    assert queried is not None
    assert queried.agent_model is None
    assert queried.requested_model == ALIAS
    assert set(queried.cost_by_model) == {UNKNOWN_MODEL_KEY}
    assert queried.total_cost_usd > 0
