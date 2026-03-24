"""Tests for extracted value_objects helpers."""

from __future__ import annotations

from decimal import Decimal

from syn_domain.contexts.orchestration._shared.value_objects import _token_cost


class TestTokenCost:
    """Tests for _token_cost helper."""

    def test_zero_count(self) -> None:
        assert _token_cost(0, Decimal("3.00")) == Decimal("0")

    def test_none_price(self) -> None:
        assert _token_cost(1000, None) == Decimal("0")

    def test_zero_price(self) -> None:
        assert _token_cost(1000, Decimal("0")) == Decimal("0")

    def test_normal_calculation(self) -> None:
        # 1000 tokens at $3 per million = $0.003
        result = _token_cost(1000, Decimal("3.00"))
        assert result == Decimal("0.003")

    def test_million_tokens(self) -> None:
        # 1M tokens at $3 per million = $3.00
        result = _token_cost(1_000_000, Decimal("3.00"))
        assert result == Decimal("3.00")
