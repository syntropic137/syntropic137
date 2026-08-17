"""Tests for CostCalculator."""

from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import (
    CostCalculator,
)
from syn_shared.pricing import (
    MODEL_PRICING_TABLE,
    UnknownModelPricingError,
    require_model_pricing,
    resolve_model_pricing,
)


@pytest.mark.unit
class TestCostCalculator:
    """Tests for CostCalculator."""

    def test_default_pricing_input_output(self) -> None:
        calc = CostCalculator()
        cost = calc.calculate_token_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-sonnet-4-20250514",
        )
        # Sonnet 4: $3 input + $15 output = $18
        assert cost == Decimal("18.00")

    def test_cache_token_costs(self) -> None:
        calc = CostCalculator()
        cost = calc.calculate_token_cost(
            input_tokens=0,
            output_tokens=0,
            cache_creation=1_000_000,
            cache_read=1_000_000,
            model="claude-sonnet-4-20250514",
        )
        # Sonnet 4: $3.75 cache write + $0.30 cache read = $4.05
        assert cost == Decimal("4.05")

    def test_unknown_model_contributes_zero_cost(self) -> None:
        """An unknown/missing model MUST NOT be priced as any real model (#788)."""
        calc = CostCalculator()
        cost = calc.calculate_token_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        assert cost == Decimal("0")

    def test_missing_model_is_not_priced(self) -> None:
        """model=None resolves to no pricing, never a guessed default."""
        calc = CostCalculator()
        assert calc.resolve_pricing(None) is None
        assert calc.resolve_pricing("totally-unknown-model") is None

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
        cost = calc.calculate_token_cost(
            input_tokens=1000, output_tokens=500, model="claude-sonnet-4-20250514"
        )
        expected = (Decimal("1000") / 1_000_000) * Decimal("3.00") + (
            Decimal("500") / 1_000_000
        ) * Decimal("15.00")
        assert cost == expected

    def test_shared_pricing_has_cache_rates(self) -> None:
        pricing = require_model_pricing("claude-sonnet-4-20250514")
        assert pricing.input_per_million == Decimal("3.00")
        assert pricing.output_per_million == Decimal("15.00")
        assert pricing.cache_creation_per_million == Decimal("3.75")
        assert pricing.cache_read_per_million == Decimal("0.30")

    # ADR-067 D4: the two tests that lived here asserted the prefix-match
    # heuristic and the unknown-model-to-Sonnet fallback. Both are removed:
    # an unrecognised snapshot is unknown, not "priced like its family", since
    # vendors reprice across snapshots (Opus 4 $15/$75 vs Opus 4.5 $5/$25).

    def test_unrecognised_snapshot_is_not_priced_by_family(self) -> None:
        assert resolve_model_pricing("claude-sonnet-4-20260101") is None
        with pytest.raises(UnknownModelPricingError):
            require_model_pricing("claude-sonnet-4-20260101")

    def test_unknown_model_is_not_priced_as_sonnet(self) -> None:
        assert resolve_model_pricing("unknown-model-123") is None
        with pytest.raises(UnknownModelPricingError):
            require_model_pricing("unknown-model-123")

    def test_all_models_have_cache_pricing(self) -> None:
        for model_id, pricing in MODEL_PRICING_TABLE.items():
            assert pricing.cache_creation_per_million > 0, (
                f"{model_id} missing cache creation pricing"
            )
            assert pricing.cache_read_per_million > 0, f"{model_id} missing cache read pricing"
