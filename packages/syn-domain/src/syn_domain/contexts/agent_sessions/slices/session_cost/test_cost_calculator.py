"""Tests for CostCalculator."""

from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import (
    CostCalculator,
)
from syn_shared.pricing import MODEL_PRICING_TABLE, get_model_pricing


@pytest.mark.unit
class TestCostCalculator:
    """Tests for CostCalculator."""

    def test_default_pricing_input_output(self) -> None:
        calc = CostCalculator()
        cost = calc.calculate_token_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # Default (Sonnet 4): $3 input + $15 output = $18
        assert cost == Decimal("18.00")

    def test_cache_token_costs(self) -> None:
        calc = CostCalculator()
        cost = calc.calculate_token_cost(
            input_tokens=0,
            output_tokens=0,
            cache_creation=1_000_000,
            cache_read=1_000_000,
        )
        # Default (Sonnet 4): $3.75 cache write + $0.30 cache read = $4.05
        assert cost == Decimal("4.05")

    def test_model_specific_pricing(self) -> None:
        calc = CostCalculator()
        cost = calc.calculate_token_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-3-opus-20240229",
        )
        # Opus 3: $15 input + $75 output = $90
        assert cost == Decimal("90.00")

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

    def test_shared_pricing_has_cache_rates(self) -> None:
        pricing = get_model_pricing("claude-sonnet-4-20250514")
        assert pricing.input_per_million == Decimal("3.00")
        assert pricing.output_per_million == Decimal("15.00")
        assert pricing.cache_creation_per_million == Decimal("3.75")
        assert pricing.cache_read_per_million == Decimal("0.30")

    def test_shared_pricing_prefix_fallback(self) -> None:
        pricing = get_model_pricing("claude-sonnet-4-20260101")
        assert pricing.model_id == "claude-sonnet-4-20250514"

    def test_shared_pricing_unknown_model_defaults_to_sonnet(self) -> None:
        pricing = get_model_pricing("unknown-model-123")
        assert pricing.model_id == "claude-sonnet-4-20250514"

    def test_all_models_have_cache_pricing(self) -> None:
        for model_id, pricing in MODEL_PRICING_TABLE.items():
            assert pricing.cache_creation_per_million > 0, f"{model_id} missing cache creation pricing"
            assert pricing.cache_read_per_million > 0, f"{model_id} missing cache read pricing"
