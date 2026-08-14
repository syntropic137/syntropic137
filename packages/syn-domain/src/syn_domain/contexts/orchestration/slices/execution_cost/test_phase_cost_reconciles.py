"""cost_by_phase must decompose total_cost_usd, not silently undercount it (#812).

The per-phase breakdown used to be a flat ``SUM(total_cost_usd) GROUP BY
phase_id``. PostgreSQL excludes NULLs from ``SUM``, so a phase whose
summaries carried no SDK cost contributed nothing - even when its model was
known and its tokens were priceable.

That was survivable while the execution total had the same blind spot. Once
#788/#795 taught the total to price null-cost rows from their own tokens,
the two numbers diverged: the breakdown summed to LESS than the total it is
supposed to decompose. Phase rows now carry model and token columns and
group on the null-cost flag, so both go through the same per-row rule.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import (
    UNATTRIBUTED_PHASE_ID,
)
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    _COST_BY_PHASE_QUERY as _BATCH_COST_BY_PHASE_QUERY,
)
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    _COST_BY_PHASE_QUERY,
    price_grouped_session_summary,
    price_phase_rows,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_OPUS_MODEL = "claude-opus-4-20250514"
_HAIKU_MODEL = "claude-3-5-haiku-20241022"
# 1M input + 1M output at Opus rates: $15.00 + $75.00
_OPUS_COST_1M_1M = Decimal("90.00")


class _FakeRow:
    def __init__(self, data: Mapping[str, object]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)


def _phase_row(
    phase_id: str | None,
    model: str | None,
    sdk_cost: Decimal | None,
    input_tokens: int = 1_000_000,
    output_tokens: int = 1_000_000,
) -> _FakeRow:
    return _FakeRow(
        {
            "phase_id": phase_id,
            "model": model,
            "total_input": input_tokens,
            "total_output": output_tokens,
            "cache_creation": 0,
            "cache_read": 0,
            "sdk_cost": sdk_cost,
            "observation_count": 1,
        }
    )


def _summary_row(
    model: str | None,
    session_id: str,
    sdk_cost: Decimal | None,
    input_tokens: int = 1_000_000,
    output_tokens: int = 1_000_000,
) -> _FakeRow:
    return _FakeRow(
        {
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
            "observation_count": 1,
        }
    )


@pytest.mark.unit
class TestPhaseCostReconcilesWithTotal:
    def test_null_cost_phase_is_priced_from_its_own_tokens(self) -> None:
        """The regression itself: a phase with no SDK cost used to vanish."""
        rows = [_phase_row("plan", _OPUS_MODEL, sdk_cost=None)]

        by_phase = price_phase_rows(rows, CostCalculator())

        assert by_phase == {"plan": _OPUS_COST_1M_1M}

    def test_breakdown_sums_to_the_execution_total(self) -> None:
        """The invariant #812 is really about.

        Same underlying summaries, viewed two ways: one phase SDK-priced,
        one not. Whatever the total says, the parts must add up to it.

        Scope: this exercises the two PRICING helpers against hand-built
        grouped rows. It does NOT execute the SQL, so it cannot prove the
        queries produce those groups - see
        ``test_phase_queries_carry_model_and_split_on_the_null_flag`` for
        the (weaker) query-text guard, and #813 for real database coverage.
        """
        summary_rows = [
            _summary_row(_HAIKU_MODEL, "session-build", sdk_cost=Decimal("3.33")),
            _summary_row(_OPUS_MODEL, "session-plan", sdk_cost=None),
        ]
        phase_rows = [
            _phase_row("build", _HAIKU_MODEL, sdk_cost=Decimal("3.33")),
            _phase_row("plan", _OPUS_MODEL, sdk_cost=None),
        ]

        grouped = price_grouped_session_summary(summary_rows, CostCalculator())
        by_phase = price_phase_rows(phase_rows, CostCalculator())

        assert sum(by_phase.values()) == grouped.total_cost

    def test_same_phase_priced_and_unpriced_groups_both_count(self) -> None:
        """One phase can produce two rows once the null-cost flag splits them."""
        rows = [
            _phase_row("plan", _OPUS_MODEL, sdk_cost=Decimal("12.50")),
            _phase_row("plan", _OPUS_MODEL, sdk_cost=None),
        ]

        by_phase = price_phase_rows(rows, CostCalculator())

        assert by_phase == {"plan": Decimal("12.50") + _OPUS_COST_1M_1M}

    def test_genuinely_unpriceable_phase_is_omitted_not_zeroed(self) -> None:
        """Unknown model and no SDK cost: say nothing rather than claim $0."""
        rows = [_phase_row("mystery", None, sdk_cost=None)]

        by_phase = price_phase_rows(rows, CostCalculator())

        assert by_phase == {}

    def test_unattributed_rows_are_bucketed_not_dropped(self) -> None:
        """A phase-less summary counts toward the total, so it must appear here.

        ``agent_events.phase_id`` is nullable. Skipping those rows was the
        second way the breakdown could fail to reconcile - caught by review
        after the first fix.
        """
        rows = [
            _phase_row("build", _HAIKU_MODEL, sdk_cost=Decimal("3.33")),
            _phase_row(None, _OPUS_MODEL, sdk_cost=Decimal("1.00")),
        ]

        by_phase = price_phase_rows(rows, CostCalculator())

        assert by_phase == {
            "build": Decimal("3.33"),
            UNATTRIBUTED_PHASE_ID: Decimal("1.00"),
        }

    def test_phase_queries_carry_model_and_split_on_the_null_flag(self) -> None:
        """Guard the SQL: a flat SUM GROUP BY phase_id reintroduces the drift.

        The pricing above is only reachable because the queries hand it
        model and token columns in split groups. That lives in SQL and
        cannot be exercised without a database, so this asserts on the
        query text - a real integration test is #813.
        """
        for query in (_COST_BY_PHASE_QUERY, _BATCH_COST_BY_PHASE_QUERY):
            assert "data->>'model' as model" in query
            assert "((data->>'total_cost_usd') IS NULL)" in query
            assert "as sdk_cost" in query
            assert "phase_cost" not in query
            # Phase-less summaries must NOT be filtered out in SQL.
            assert "phase_id IS NOT NULL" not in query
