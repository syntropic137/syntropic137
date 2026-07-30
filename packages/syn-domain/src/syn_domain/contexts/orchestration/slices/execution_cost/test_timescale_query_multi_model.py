"""Regression test: TimescaleExecutionCostQuery.calculate() prices per model.

Exercises the full ``calculate()`` path (not just the pricing helper) against
a mocked connection, for an in-progress execution (no session_summary yet)
whose sessions span two different models.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    TimescaleExecutionCostQuery,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_OPUS_MODEL = "claude-opus-4-20250514"
_HAIKU_MODEL = "claude-3-5-haiku-20241022"
_OPUS_COST_1M_1M = Decimal("90.00")
_HAIKU_COST_1M_1M = Decimal("6.00")


class _FakeRow:
    """Fake asyncpg Record supporting both bracket and .get() access."""

    def __init__(self, data: Mapping[str, object]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)


def _grouped_token_rows() -> list[_FakeRow]:
    return [
        _FakeRow(
            {
                "model": _OPUS_MODEL,
                "total_input": 1_000_000,
                "total_output": 1_000_000,
                "cache_creation": 0,
                "cache_read": 0,
                "session_count": 1,
                "session_ids": ["session-opus"],
                "started_at": None,
                "last_observation": None,
            }
        ),
        _FakeRow(
            {
                "model": _HAIKU_MODEL,
                "total_input": 1_000_000,
                "total_output": 1_000_000,
                "cache_creation": 0,
                "cache_read": 0,
                "session_count": 1,
                "session_ids": ["session-haiku"],
                "started_at": None,
                "last_observation": None,
            }
        ),
    ]


def _make_mock_pool() -> MagicMock:
    """No session_summary rows exist yet; only grouped token_usage rows."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)  # no session_summary
    conn.fetch = AsyncMock(return_value=_grouped_token_rows())
    conn.fetchval = AsyncMock(return_value=0)

    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=None)
        )
    )
    return pool


@pytest.mark.unit
@pytest.mark.asyncio
async def test_in_progress_execution_prices_each_model_group() -> None:
    pool = _make_mock_pool()
    query = TimescaleExecutionCostQuery(pool)

    result = await query.calculate("exec-multi")

    assert result is not None
    assert result.total_cost_usd == _OPUS_COST_1M_1M + _HAIKU_COST_1M_1M
    assert result.cost_by_model == {
        _OPUS_MODEL: _OPUS_COST_1M_1M,
        _HAIKU_MODEL: _HAIKU_COST_1M_1M,
    }
    assert result.unpriced_observation_count == 0
    assert result.input_tokens == 2_000_000
