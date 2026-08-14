"""Regression tests: completed-execution session_summary path prices per model.

Review finding on #788 (structural follow-up, third occurrence of the same
bug class): the session_summary aggregation used by *completed* executions
flattened ``SUM(total_cost_usd)`` across all sessions in an execution before
this fix, with two concrete failure modes:

- All-NULL case: every summary's ``total_cost_usd`` is NULL -> ``SUM``
  returns NULL -> the old fallback priced with no model -> $0 for a known
  Opus/Haiku execution.
- Partial-NULL case (worse): only some summaries are NULL -> PostgreSQL
  silently excludes those rows from ``SUM`` -> a plausible-looking but
  wrong partial total.

The fix groups session_summary rows by model (mirroring the token_usage
fallback path) and prices each group: use ``sdk_cost`` when present
(authoritative), else price that group's own tokens with that group's own
model. These tests exercise ``price_grouped_session_summary`` directly and
the full ``TimescaleExecutionCostQuery.calculate()`` path.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    TimescaleExecutionCostQuery,
    price_grouped_session_summary,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_OPUS_MODEL = "claude-opus-4-20250514"
_HAIKU_MODEL = "claude-3-5-haiku-20241022"
# 1M input + 1M output tokens at Opus rates: $15.00 + $75.00 = $90.00
_OPUS_COST_1M_1M = Decimal("90.00")
# 1M input + 1M output tokens at Haiku rates: $1.00 + $5.00 = $6.00
_HAIKU_COST_1M_1M = Decimal("6.00")


class _FakeRow:
    """Fake asyncpg Record supporting both bracket and .get() access."""

    def __init__(self, data: Mapping[str, object]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)


def _summary_group_row(
    model: str | None,
    session_id: str,
    sdk_cost: Decimal | None,
    input_tokens: int = 1_000_000,
    output_tokens: int = 1_000_000,
    observation_count: int = 1,
) -> _FakeRow:
    return _FakeRow(
        {
            "execution_id": "exec-summary",
            "model": model,
            "total_input": input_tokens,
            "total_output": output_tokens,
            "cache_creation": 0,
            "cache_read": 0,
            "sdk_cost": sdk_cost,
            "duration_ms_val": 0,
            "total_turns": 1,
            "session_count": 1,
            "session_ids": [session_id],
            "started_at": None,
            "completed_at": None,
            "observation_count": observation_count,
        }
    )


@pytest.mark.unit
class TestPriceGroupedSessionSummary:
    def test_all_null_sdk_cost_known_model_is_priced_not_zero(self) -> None:
        """All summaries NULL -> priced from that group's tokens, not $0."""
        rows = [_summary_group_row(_OPUS_MODEL, "session-opus", sdk_cost=None)]

        grouped = price_grouped_session_summary(rows, CostCalculator())

        assert grouped.total_cost == _OPUS_COST_1M_1M
        assert grouped.cost_by_model == {_OPUS_MODEL: _OPUS_COST_1M_1M}
        assert grouped.unpriced_observation_count == 0

    def test_partial_null_sdk_cost_does_not_silently_drop_the_null_group(self) -> None:
        """One group NULL, one populated -> total is populated + priced-NULL, not just populated."""
        rows = [
            _summary_group_row(_OPUS_MODEL, "session-opus", sdk_cost=Decimal("12.50")),
            _summary_group_row(_HAIKU_MODEL, "session-haiku", sdk_cost=None),
        ]

        grouped = price_grouped_session_summary(rows, CostCalculator())

        # Populated sdk_cost is used verbatim; the NULL group is priced from
        # its own tokens/model rather than vanishing from the SUM.
        assert grouped.total_cost == Decimal("12.50") + _HAIKU_COST_1M_1M
        assert grouped.cost_by_model == {
            _OPUS_MODEL: Decimal("12.50"),
            _HAIKU_MODEL: _HAIKU_COST_1M_1M,
        }
        assert grouped.unpriced_observation_count == 0

    def test_multi_model_mixed_null_and_populated_prices_each_correctly(self) -> None:
        """Opus (populated) + Haiku (NULL) -> each priced with its own rate."""
        rows = [
            _summary_group_row(_OPUS_MODEL, "session-opus", sdk_cost=None),
            _summary_group_row(_HAIKU_MODEL, "session-haiku", sdk_cost=Decimal("3.33")),
        ]

        grouped = price_grouped_session_summary(rows, CostCalculator())

        assert grouped.cost_by_model == {
            _OPUS_MODEL: _OPUS_COST_1M_1M,
            _HAIKU_MODEL: Decimal("3.33"),
        }
        assert grouped.total_cost == _OPUS_COST_1M_1M + Decimal("3.33")
        assert set(grouped.session_ids) == {"session-opus", "session-haiku"}

    def test_unpriced_observation_count_reflects_real_observations_not_group_count(self) -> None:
        """N unknown-model observations in one group -> unpriced_observation_count == N."""
        rows = [
            _summary_group_row(None, "session-unknown", sdk_cost=None, observation_count=10_000)
        ]

        grouped = price_grouped_session_summary(rows, CostCalculator())

        assert grouped.total_cost == Decimal("0")
        assert grouped.unpriced_observation_count == 10_000

    def test_unknown_model_group_missing_observation_count_defaults_to_one(self) -> None:
        """Hand-built rows without observation_count still count as 1, not dropped."""
        rows = [_summary_group_row(None, "session-unknown", sdk_cost=None, observation_count=1)]

        grouped = price_grouped_session_summary(rows, CostCalculator())

        assert grouped.unpriced_observation_count == 1


def _fake_pool(summary_rows: list[_FakeRow]) -> MagicMock:
    async def fetch_side_effect(query: str, _execution_id: str, _event_type: str) -> list[_FakeRow]:
        # _COST_BY_PHASE_QUERY groups by phase_id; no phase data in these tests.
        if "phase_id" in query:
            return []
        return summary_rows

    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=fetch_side_effect)
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
class TestTimescaleExecutionCostQueryCompletedSummaryPath:
    """Exercises the full ``calculate()`` path for completed (session_summary) executions."""

    async def test_all_null_summaries_known_model_prices_correctly(self) -> None:
        rows = [_summary_group_row(_OPUS_MODEL, "session-opus", sdk_cost=None)]
        pool = _fake_pool(rows)
        query = TimescaleExecutionCostQuery(pool)

        result = await query.calculate("exec-summary")

        assert result is not None
        assert result.total_cost_usd == _OPUS_COST_1M_1M
        assert result.unpriced_observation_count == 0

    async def test_mixed_null_and_populated_multi_model_execution(self) -> None:
        rows = [
            _summary_group_row(_OPUS_MODEL, "session-opus", sdk_cost=None),
            _summary_group_row(_HAIKU_MODEL, "session-haiku", sdk_cost=Decimal("3.33")),
        ]
        pool = _fake_pool(rows)
        query = TimescaleExecutionCostQuery(pool)

        result = await query.calculate("exec-summary")

        assert result is not None
        assert result.total_cost_usd == _OPUS_COST_1M_1M + Decimal("3.33")
        assert result.cost_by_model == {
            _OPUS_MODEL: _OPUS_COST_1M_1M,
            _HAIKU_MODEL: Decimal("3.33"),
        }
        assert result.unpriced_observation_count == 0
        assert result.input_tokens == 2_000_000


@pytest.mark.unit
class TestSameModelMixedNullCosts:
    """Codex review of #795: the model-only GROUP BY left one case unfixed.

    Splitting rows by model separates priced from unpriced summaries only
    when they use DIFFERENT models. Two summaries on the SAME model - one
    SDK-priced, one not - collapsed into a single group whose
    ``SUM(total_cost_usd)`` is non-NULL, so the token fallback never fired
    even though the group's token totals included the unpriced row. Tokens
    from both, cost from one: a silent undercount.

    The queries now also group on ``total_cost_usd IS NULL``, so those rows
    arrive as two groups. These tests pin both halves: the SQL keeps the
    split, and the Python merge sums the split groups correctly.
    """

    def test_same_model_priced_and_unpriced_groups_both_count(self) -> None:
        """Same model, two groups: SDK cost + token-priced cost, not just the SDK one."""
        rows = [
            _summary_group_row(_OPUS_MODEL, "session-priced", sdk_cost=Decimal("12.50")),
            _summary_group_row(_OPUS_MODEL, "session-unpriced", sdk_cost=None),
        ]

        grouped = price_grouped_session_summary(rows, CostCalculator())

        expected = Decimal("12.50") + _OPUS_COST_1M_1M
        assert grouped.total_cost == expected
        assert grouped.cost_by_model == {_OPUS_MODEL: expected}
        assert grouped.unpriced_observation_count == 0
        # Tokens from BOTH rows are counted, which is what made the old
        # behaviour an undercount rather than a simple omission.
        assert grouped.input_tokens == 2_000_000

    def test_summary_queries_group_on_the_null_cost_flag(self) -> None:
        """Guard the SQL itself: a model-only GROUP BY reintroduces the undercount.

        The merge above is only correct because the query hands it separate
        rows for priced and unpriced summaries. That split lives in SQL and
        cannot be exercised without a database, so assert on the query text.
        """
        from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
            _LIST_ALL_FROM_SUMMARY_QUERY,
        )
        from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
            _SESSION_SUMMARY_QUERY,
        )

        assert "((data->>'total_cost_usd') IS NULL)" in _SESSION_SUMMARY_QUERY
        assert "((a.data->>'total_cost_usd') IS NULL)" in _LIST_ALL_FROM_SUMMARY_QUERY
