"""#2145 B2b: recorded execution and session costs price 1-hour cache writes at the 1-hour rate.

A ``TOKEN_USAGE`` row stores every cache write in ``cache_creation_tokens`` and
the 1-hour share beside it in ``cache_creation_1h_tokens`` (B2a, #2331). These
tests drive that row through the things that READ it - the two cost
projections and the Timescale grouped queries - and check the dollars that
come out, not the split helper in isolation.

Opus 5.5 writes the cache at $5.00/MTok for 5 minutes and $8.00/MTok for 1 hour.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_adapters.subscriptions.projection_adapters import (
    ExecutionCostAdapter,
    SessionCostAdapter,
)
from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.agent_sessions.slices.session_cost import (
    query_service as session_query_service,
)
from syn_domain.contexts.agent_sessions.slices.session_cost import (
    timescale_query as session_timescale,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import (
    SessionCostProjection,
)
from syn_domain.contexts.orchestration.slices.execution_cost import (
    query_service as execution_query_service,
)
from syn_domain.contexts.orchestration.slices.execution_cost import (
    timescale_query as execution_timescale,
)
from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
    ExecutionCostProjection,
)
from syn_shared.agents import ModelId

if TYPE_CHECKING:
    from collections.abc import Mapping

    import asyncpg

pytestmark = pytest.mark.unit

_OPUS = ModelId.CLAUDE_OPUS_5_5.value
_MILLION = 1_000_000

#: One row, every cache write 1-hour: $8.00, where pricing it all at 5 minutes said $5.00.
_ALL_1H = {"cache_creation_tokens": _MILLION, "cache_creation_1h_tokens": _MILLION}
#: A row written before B2a: no 1-hour key at all.
_LEGACY = {"cache_creation_tokens": _MILLION}
#: 600k 1-hour + 400k 5-minute: 0.6 * 8.00 + 0.4 * 5.00 = 6.80.
_MIXED = {"cache_creation_tokens": _MILLION, "cache_creation_1h_tokens": 600_000}

_CASES = [
    pytest.param(_ALL_1H, Decimal("8.00"), _MILLION, id="all-1h"),
    pytest.param(_LEGACY, Decimal("5.00"), 0, id="legacy-row"),
    pytest.param(_MIXED, Decimal("6.80"), 600_000, id="mixed"),
]


def _token_usage(cache: Mapping[str, int]) -> dict[str, str | dict[str, str | int]]:
    return {
        "session_id": "session-1",
        "execution_id": "exec-1",
        "observation_type": ObservationType.TOKEN_USAGE.value,
        "event_type": ObservationType.TOKEN_USAGE.value,
        "data": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "model": _OPUS,
            **cache,
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(("cache", "expected", "one_hour"), _CASES)
async def test_execution_cost_projection_prices_recorded_1h_writes(
    cache: Mapping[str, int], expected: Decimal, one_hour: int
) -> None:
    projection = ExecutionCostProjection(InMemoryProjectionStore())

    await projection.on_agent_observation(_token_usage(cache))

    cost = await projection.get_execution_cost("exec-1")
    assert cost is not None
    assert cost.total_cost_usd == expected
    assert cost.cost_by_model[_OPUS] == expected
    assert cost.cache_creation_tokens == _MILLION
    assert cost.cache_creation_1h_tokens == one_hour


@pytest.mark.asyncio
@pytest.mark.parametrize(("cache", "expected", "one_hour"), _CASES)
async def test_session_cost_projection_prices_recorded_1h_writes(
    cache: Mapping[str, int], expected: Decimal, one_hour: int
) -> None:
    projection = SessionCostProjection(InMemoryProjectionStore())

    await projection.on_agent_observation(_token_usage(cache))

    cost = await projection.get_session_cost("session-1")
    assert cost is not None
    assert cost.total_cost_usd == expected
    assert cost.cache_creation_tokens == _MILLION
    assert cost.cache_creation_1h_tokens == one_hour


@pytest.mark.asyncio
async def test_legacy_row_prices_exactly_as_the_5_minute_total() -> None:
    """A row with no 1-hour key costs exactly what pricing the total at 5 minutes did."""
    before = CostCalculator().resolve_pricing(_OPUS)
    assert before is not None
    expected = before.calculate_cost(0, 0, _MILLION, 0)

    execution = ExecutionCostProjection(InMemoryProjectionStore())
    session = SessionCostProjection(InMemoryProjectionStore())
    await execution.on_agent_observation(_token_usage(_LEGACY))
    await session.on_agent_observation(_token_usage(_LEGACY))

    execution_cost = await execution.get_execution_cost("exec-1")
    session_cost = await session.get_session_cost("session-1")
    assert execution_cost is not None
    assert session_cost is not None
    assert execution_cost.total_cost_usd == expected
    assert session_cost.total_cost_usd == expected
    assert execution_cost.cache_creation_1h_tokens == 0
    assert session_cost.cache_creation_1h_tokens == 0


@pytest.mark.asyncio
async def test_cache_creation_1h_tokens_sums_across_turns_and_survives_the_store() -> None:
    """The counter is summed per turn and read back from the stored dict, not just held in memory."""
    store = InMemoryProjectionStore()
    projection = ExecutionCostProjection(store)

    await projection.on_agent_observation(_token_usage(_MIXED))
    await projection.on_agent_observation(_token_usage(_ALL_1H))

    cost = await ExecutionCostProjection(store).get_execution_cost("exec-1")
    assert cost is not None
    assert cost.cache_creation_1h_tokens == 1_600_000
    assert cost.total_cost_usd == Decimal("14.80")


# --- Timescale read paths ---------------------------------------------------


#: A column value the grouped token_usage SQL can return.
_Cell = int | str | list[str] | None


class _FakeRow:
    """An asyncpg Record as the grouped token_usage SQL returns one."""

    def __init__(self, data: Mapping[str, _Cell]) -> None:
        self._data = dict(data)

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)


def _grouped_row(cache_creation: int, cache_creation_1h: int | None) -> asyncpg.Record:
    row: dict[str, _Cell] = {
        "model": _OPUS,
        "agent_model": _OPUS,
        "total_input": 0,
        "total_output": 0,
        "cache_creation": cache_creation,
        "cache_read": 0,
        "session_ids": ["session-1"],
        "observation_count": 1,
        "started_at": None,
        "last_observation": None,
        "workspace_id": None,
        "execution_id": "exec-1",
        "phase_id": None,
    }
    if cache_creation_1h is not None:
        row["cache_creation_1h"] = cache_creation_1h
    return _FakeRow(row)  # type: ignore[return-value]


_GROUPED_CASES = [
    pytest.param(_MILLION, _MILLION, Decimal("8.00"), id="all-1h"),
    pytest.param(_MILLION, None, Decimal("5.00"), id="legacy-no-column"),
    pytest.param(_MILLION, 600_000, Decimal("6.80"), id="mixed"),
]


@pytest.mark.parametrize(("total", "one_hour", "expected"), _GROUPED_CASES)
def test_execution_grouped_token_usage_prices_the_summed_1h_share(
    total: int, one_hour: int | None, expected: Decimal
) -> None:
    grouped = execution_timescale.price_grouped_token_usage(
        [_grouped_row(total, one_hour)], CostCalculator()
    )

    assert grouped.total_cost == expected
    assert grouped.cache_creation_1h == (one_hour or 0)


@pytest.mark.parametrize(("total", "one_hour", "expected"), _GROUPED_CASES)
def test_session_grouped_rows_price_the_summed_1h_share(
    total: int, one_hour: int | None, expected: Decimal
) -> None:
    totals = session_timescale.price_session_rows(
        [_grouped_row(total, one_hour)], CostCalculator(), "session-1"
    )

    assert totals is not None
    assert totals.total_cost == expected
    assert totals.cache_creation_1h == (one_hour or 0)
    # The token-type split prices the same row the same way, so it still sums to the total.
    assert totals.cost_by_token_type is not None
    assert totals.cost_by_token_type.cache_creation_usd == expected


_SUMS_1H = "SUM(COALESCE((data->>'cache_creation_1h_tokens')::int, 0)) as cache_creation_1h"


@pytest.mark.parametrize(
    "sql",
    [
        pytest.param(execution_timescale._TOKEN_USAGE_FALLBACK_QUERY, id="execution-fallback"),
        pytest.param(
            execution_query_service._LIST_ALL_FROM_TOKEN_USAGE_QUERY, id="execution-list-all"
        ),
        pytest.param(execution_query_service._BY_IDS_FROM_TOKEN_USAGE_QUERY, id="execution-by-ids"),
        pytest.param(session_timescale._TOKEN_USAGE_FALLBACK_BATCH_QUERY, id="session-fallback"),
        pytest.param(session_query_service._LIST_ALL_FROM_TOKEN_USAGE_QUERY, id="session-list-all"),
    ],
)
def test_grouped_token_usage_sql_sums_the_1h_share(sql: str) -> None:
    """Every grouped token_usage query hands its pricer the 1-hour share, 0 for legacy rows."""
    assert _SUMS_1H in sql


def test_cost_projection_versions_are_bumped_for_the_1h_reprice() -> None:
    """The stored cost read models change shape and value, so both must replay (#2145 B2b)."""
    assert ExecutionCostAdapter.VERSION >= 2
    assert SessionCostAdapter.VERSION >= 2
