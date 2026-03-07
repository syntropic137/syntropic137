"""Tests for CostCalculator."""

from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import (
    DEFAULT_PRICING,
    CostCalculator,
    ModelPricing,
)


@pytest.mark.unit
class TestCostCalculator:
    """Tests for CostCalculator."""

    def test_default_pricing_input_output(self) -> None:
        calc = CostCalculator()
        cost = calc.calculate_token_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        assert cost == Decimal("18.00")

    def test_cache_token_costs(self) -> None:
        calc = CostCalculator()
        cost = calc.calculate_token_cost(
            input_tokens=0,
            output_tokens=0,
            cache_creation=1_000_000,
            cache_read=1_000_000,
        )
        assert cost == Decimal("4.05")

    def test_custom_pricing(self) -> None:
        pricing = ModelPricing(
            input_per_million=Decimal("10.00"),
            output_per_million=Decimal("30.00"),
            cache_write_per_million=Decimal("0"),
            cache_read_per_million=Decimal("0"),
        )
        calc = CostCalculator(pricing)
        cost = calc.calculate_token_cost(input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == Decimal("40.00")

    def test_zero_tokens(self) -> None:
        calc = CostCalculator()
        cost = calc.calculate_token_cost(0, 0, 0, 0)
        assert cost == Decimal("0")

    def test_small_token_counts(self) -> None:
        calc = CostCalculator()
        cost = calc.calculate_token_cost(input_tokens=1000, output_tokens=500)
        expected = (Decimal("1000") / 1_000_000) * Decimal("3.00") + (
            Decimal("500") / 1_000_000
        ) * Decimal("15.00")
        assert cost == expected

    def test_default_pricing_values(self) -> None:
        assert DEFAULT_PRICING.input_per_million == Decimal("3.00")
        assert DEFAULT_PRICING.output_per_million == Decimal("15.00")
        assert DEFAULT_PRICING.cache_write_per_million == Decimal("3.75")
        assert DEFAULT_PRICING.cache_read_per_million == Decimal("0.30")
