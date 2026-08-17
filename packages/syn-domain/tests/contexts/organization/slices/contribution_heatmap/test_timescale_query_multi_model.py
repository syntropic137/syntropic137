"""Pin the heatmap's per-model pricing decision.

A day's heatmap bucket aggregates activity across every session and every
model active that day. There is no single "correct" model to price the
whole day's tokens at, so ``TimescaleHeatmapQuery`` groups token_usage rows
by (day, model) and prices each group with its own rate - a day with an
unresolvable model's tokens surfaces those as ``unpriced_tokens`` instead of
silently multiplying mixed-model tokens by one model's rate (issue #788).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
    TimescaleHeatmapQuery,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_OPUS_MODEL = "claude-opus-4-20250514"
_HAIKU_MODEL = "claude-3-5-haiku-20241022"
_OPUS_COST_1M_1M = Decimal("90.00")
# Haiku 3.5 is $0.80/$4.00 per 1M (was wrongly carrying Haiku 4.5's
# $1/$5 until #816). 1M in + 1M out = $4.80.
_HAIKU_COST_1M_1M = Decimal("4.80")


class _FakeRow:
    def __init__(self, data: Mapping[str, object]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)


def _day_row(day: date) -> _FakeRow:
    """Row shaped like _METRIC_COLUMNS - no model breakdown here."""
    return _FakeRow(
        {
            "day": day,
            "sessions": 2,
            "executions": 1,
            "commits": 0,
            "input_tokens": 2_000_000,
            "output_tokens": 2_000_000,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        }
    )


def _model_row(day: date, model: str | None) -> _FakeRow:
    """Row shaped like _MODEL_TOKEN_COLUMNS - one model's totals for the day."""
    return _FakeRow(
        {
            "day": day,
            "model": model,
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        }
    )


def _make_mock_pool(day_rows: list[_FakeRow], model_rows: list[_FakeRow]) -> MagicMock:
    """Differentiate the two `conn.fetch` calls by inspecting the query text."""

    async def _fetch(query: str, *_args: object) -> list[_FakeRow]:
        if "GROUP BY day, model" in query:
            return model_rows
        return day_rows

    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=_fetch)

    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=None)
        )
    )
    return pool


@pytest.mark.unit
@pytest.mark.asyncio
async def test_day_with_two_models_prices_each_at_its_own_rate() -> None:
    day = date(2026, 4, 1)
    pool = _make_mock_pool(
        day_rows=[_day_row(day)],
        model_rows=[_model_row(day, _OPUS_MODEL), _model_row(day, _HAIKU_MODEL)],
    )
    query = TimescaleHeatmapQuery(pool)

    buckets = await query.query(start=day, end=day, execution_ids=None)

    assert len(buckets) == 1
    breakdown = buckets[0].breakdown
    assert breakdown["cost_usd"] == pytest.approx(float(_OPUS_COST_1M_1M + _HAIKU_COST_1M_1M))
    assert breakdown["unpriced_tokens"] == 0.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_day_with_unresolvable_model_surfaces_unpriced_tokens_not_a_guess() -> None:
    day = date(2026, 4, 2)
    pool = _make_mock_pool(
        day_rows=[_day_row(day)],
        model_rows=[_model_row(day, _OPUS_MODEL), _model_row(day, None)],
    )
    query = TimescaleHeatmapQuery(pool)

    buckets = await query.query(start=day, end=day, execution_ids=None)

    breakdown = buckets[0].breakdown
    # Only the priceable (Opus) group contributes to cost_usd - the unknown
    # group's tokens are surfaced separately, never priced as Opus or any
    # other default model.
    assert breakdown["cost_usd"] == pytest.approx(float(_OPUS_COST_1M_1M))
    assert breakdown["unpriced_tokens"] == 2_000_000.0
