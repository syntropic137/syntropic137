"""Harness-reported costs reach the read models as clean Decimals.

The Claude CLI reports cost as a JS double, stored verbatim in agent_events.
The live v0.30.0-beta.7 API served ``0.30566780000000005`` for a phase and
``0.43809100000000005`` for its execution. Every read path now canonicalises
through ``syn_shared.pricing.canonical_cost_usd``; these tests pin each entry
point to the exact live value.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions.canonical_usage import price_canonical_row
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    price_grouped_session_summary,
    price_phase_rows,
)

pytestmark = pytest.mark.unit

# asyncpg's numeric read of the stored JSON text, noise included.
LIVE_PHASE_1 = Decimal("0.30566780000000005")
LIVE_PHASE_2 = Decimal("0.13242320000000001")
_MODEL = "claude-opus-5-5"


_Cell = Decimal | float | int | str | list[str] | None


class _FakeRow:
    """Duck-types the two ``asyncpg.Record`` methods the pricing code calls."""

    def __init__(self, data: dict[str, _Cell]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)


def _phase_row(phase_id: str, sdk_cost: Decimal) -> _FakeRow:
    return _FakeRow(
        {
            "phase_id": phase_id,
            "model": _MODEL,
            "total_input": 10,
            "total_output": 10,
            "cache_creation": 0,
            "cache_read": 0,
            "sdk_cost": sdk_cost,
            "observation_count": 1,
        }
    )


def _summary_row(session_id: str, sdk_cost: Decimal) -> _FakeRow:
    return _FakeRow(
        {
            "model": _MODEL,
            "total_input": 10,
            "total_output": 10,
            "cache_creation": 0,
            "cache_read": 0,
            "sdk_cost": sdk_cost,
            "duration_ms_val": 0,
            "total_turns": 1,
            "session_ids": [session_id],
            "started_at": None,
            "completed_at": None,
            "observation_count": 1,
        }
    )


def test_canonical_row_vendor_cost_is_clean() -> None:
    row = {
        "vendor_cost_usd": LIVE_PHASE_1,
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
    }
    cost = price_canonical_row(row, CostCalculator()).cost
    assert str(cost) == "0.3056678"


def test_canonical_row_vendor_cost_from_json_float_is_clean() -> None:
    row = {
        "vendor_cost_usd": 0.30566780000000005,
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
    }
    assert str(price_canonical_row(row, CostCalculator()).cost) == "0.3056678"


def test_execution_phase_and_total_are_clean() -> None:
    """The exact live shape: two noisy phase costs, one noisy total."""
    phases = price_phase_rows(
        [_phase_row("p1", LIVE_PHASE_1), _phase_row("p2", LIVE_PHASE_2)],  # type: ignore[list-item]  # duck-typed asyncpg.Record
        CostCalculator(),
    )
    grouped = price_grouped_session_summary(
        [_summary_row("s1", LIVE_PHASE_1), _summary_row("s2", LIVE_PHASE_2)],  # type: ignore[list-item]  # duck-typed asyncpg.Record
        CostCalculator(),
    )
    cost = ExecutionCost(
        execution_id="exec-105b88d56234",
        total_cost_usd=grouped.total_cost,
        cost_by_phase=phases.cost_by_phase,
        cost_by_model=grouped.cost_by_model,
    )
    assert str(cost.cost_by_phase["p1"]) == "0.3056678"
    assert str(cost.cost_by_phase["p2"]) == "0.1324232"
    assert str(cost.total_cost_usd) == "0.438091"
    assert {str(v) for v in cost.cost_by_model.values()} == {"0.438091"}


def test_summed_sql_numeric_is_clean() -> None:
    """A SQL SUM over both stored texts keeps both tails; the read model drops them."""
    cost = ExecutionCost(execution_id="e", total_cost_usd=LIVE_PHASE_1 + LIVE_PHASE_2)
    assert str(LIVE_PHASE_1 + LIVE_PHASE_2) == "0.43809100000000006"
    assert str(cost.total_cost_usd) == "0.438091"


def test_round_numbers_keep_no_exponent() -> None:
    cost = ExecutionCost(execution_id="e", total_cost_usd=Decimal("100.0000"))
    assert str(cost.total_cost_usd) == "100"
    zero = ExecutionCost(execution_id="e")
    assert str(zero.total_cost_usd) == "0"


def test_session_cost_is_clean() -> None:
    session = SessionCost(
        session_id="036cd2ca-dc4a-4b71-9eee-6d5d3b4cc2b0",
        total_cost_usd=LIVE_PHASE_1,
        token_cost_usd=LIVE_PHASE_1,
        cost_by_model={_MODEL: LIVE_PHASE_1},
    )
    assert str(session.total_cost_usd) == "0.3056678"
    assert str(session.token_cost_usd) == "0.3056678"
    assert str(session.cost_by_model[_MODEL]) == "0.3056678"


def test_round_trip_through_storage_stays_clean() -> None:
    restored = ExecutionCost.from_dict(
        ExecutionCost(execution_id="e", total_cost_usd=LIVE_PHASE_1).to_dict()
    )
    assert str(restored.total_cost_usd) == "0.3056678"
