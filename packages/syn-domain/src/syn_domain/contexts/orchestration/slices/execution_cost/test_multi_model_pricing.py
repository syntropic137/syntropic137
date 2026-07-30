"""Regression tests: execution cost prices each model group correctly.

Issue #788 (structural follow-up): an execution can span multiple
sessions/phases on different models (e.g. an Opus planning phase followed by
a Haiku worker phase). The token_usage fallback path (used before a
session_summary lands) used to flatten every session's tokens into one SUM
and price them as a single model - or, after the first #788 fix, silently
drop to $0 for the whole execution the moment any session's model was
unresolvable. Both are wrong: each model group must be priced with its own
rate, and only genuinely unpriceable groups should contribute $0.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import pytest

from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostQueryService,
)
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    price_grouped_token_usage,
)

_FakeRow = Mapping[str, object]

_OPUS_MODEL = "claude-opus-4-20250514"
_HAIKU_MODEL = "claude-3-5-haiku-20241022"

# 1M input + 1M output tokens at Opus rates: $15.00 + $75.00 = $90.00
_OPUS_COST_1M_1M = Decimal("90.00")
# 1M input + 1M output tokens at Haiku rates: $1.00 + $5.00 = $6.00
_HAIKU_COST_1M_1M = Decimal("6.00")


def _group_row(
    model: str | None,
    session_id: str,
    input_tokens: int = 1_000_000,
    output_tokens: int = 1_000_000,
) -> _FakeRow:
    return {
        "execution_id": "exec-multi",
        "model": model,
        "total_input": input_tokens,
        "total_output": output_tokens,
        "cache_creation": 0,
        "cache_read": 0,
        "session_count": 1,
        "session_ids": [session_id],
        "started_at": None,
        "last_observation": None,
    }


@pytest.mark.unit
class TestPriceGroupedTokenUsage:
    def test_prices_each_model_group_with_its_own_rate(self) -> None:
        from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import (
            CostCalculator,
        )

        rows = [
            _group_row(_OPUS_MODEL, "session-opus"),
            _group_row(_HAIKU_MODEL, "session-haiku"),
        ]

        grouped = price_grouped_token_usage(rows, CostCalculator())

        assert grouped.cost_by_model == {
            _OPUS_MODEL: _OPUS_COST_1M_1M,
            _HAIKU_MODEL: _HAIKU_COST_1M_1M,
        }
        assert grouped.total_cost == _OPUS_COST_1M_1M + _HAIKU_COST_1M_1M
        assert grouped.unpriced_observation_count == 0
        assert set(grouped.session_ids) == {"session-opus", "session-haiku"}
        assert grouped.input_tokens == 2_000_000

    def test_unknown_model_group_is_unpriced_not_dropped_or_guessed(self) -> None:
        from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import (
            CostCalculator,
        )

        rows = [
            _group_row(_OPUS_MODEL, "session-opus"),
            _group_row(None, "session-unknown"),
        ]

        grouped = price_grouped_token_usage(rows, CostCalculator())

        # The known group is still priced correctly...
        assert grouped.cost_by_model == {_OPUS_MODEL: _OPUS_COST_1M_1M}
        assert grouped.total_cost == _OPUS_COST_1M_1M
        # ...and the unknown group is counted as unpriced, not silently
        # dropped from session_count/token totals and not guessed at.
        assert grouped.unpriced_observation_count == 1
        assert set(grouped.session_ids) == {"session-opus", "session-unknown"}
        assert grouped.input_tokens == 2_000_000


@pytest.mark.unit
class TestExecutionCostQueryServiceBuildFromTokenUsageMultiModel:
    def test_execution_with_two_models_prices_each_correctly(self) -> None:
        service = ExecutionCostQueryService(pool=None)  # type: ignore[arg-type]

        rows = [
            _group_row(_OPUS_MODEL, "session-opus"),
            _group_row(_HAIKU_MODEL, "session-haiku"),
        ]

        result = service._build_from_token_usage("exec-multi", rows, tool_counts={})

        assert result.total_cost_usd == _OPUS_COST_1M_1M + _HAIKU_COST_1M_1M
        assert result.cost_by_model == {
            _OPUS_MODEL: _OPUS_COST_1M_1M,
            _HAIKU_MODEL: _HAIKU_COST_1M_1M,
        }
        assert result.unpriced_observation_count == 0
        assert result.session_count == 2

    def test_one_unresolvable_model_group_does_not_zero_the_whole_execution(self) -> None:
        service = ExecutionCostQueryService(pool=None)  # type: ignore[arg-type]

        rows = [
            _group_row(_OPUS_MODEL, "session-opus"),
            _group_row(None, "session-unknown"),
        ]

        result = service._build_from_token_usage("exec-multi", rows, tool_counts={})

        assert result.total_cost_usd == _OPUS_COST_1M_1M
        assert result.unpriced_observation_count == 1
