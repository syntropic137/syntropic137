"""Tests for TokenAccumulator."""

from __future__ import annotations

from decimal import Decimal

from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)


class TestTokenAccumulator:
    def test_initial_state(self) -> None:
        acc = TokenAccumulator()
        assert acc.input_tokens == 0
        assert acc.output_tokens == 0
        assert acc.total_tokens == 0
        assert acc.estimate_cost() == Decimal("0")

    def test_record_accumulates(self) -> None:
        acc = TokenAccumulator()
        acc.record(100, 200)
        acc.record(50, 100)
        assert acc.input_tokens == 150
        assert acc.output_tokens == 300
        assert acc.total_tokens == 450

    def test_estimate_cost(self) -> None:
        acc = TokenAccumulator()
        acc.record(1_000_000, 1_000_000)
        cost = acc.estimate_cost()
        # 1M input * $3/M + 1M output * $15/M = $18
        assert cost == Decimal("18.00")

    def test_estimate_cost_zero_tokens(self) -> None:
        acc = TokenAccumulator()
        assert acc.estimate_cost() == Decimal("0")
