"""Tests for GPT-5.6 pricing resolution."""

from decimal import Decimal

from syn_shared.pricing import (
    calculate_cost,
    get_model_pricing,
    resolve_model_pricing,
)


def test_gpt_5_6_resolves_to_codex_pricing() -> None:
    pricing = resolve_model_pricing("gpt-5.6")

    assert pricing is not None
    assert pricing.model_id == "gpt-5.6"
    assert pricing.input_per_million == Decimal("15.0")
    assert pricing.output_per_million == Decimal("60.0")
    assert pricing.cache_read_per_million == Decimal("1.5")


def test_unknown_model_returns_none_from_strict_resolver() -> None:
    assert resolve_model_pricing("unknown-model") is None


def test_non_strict_pricing_retains_legacy_fallbacks() -> None:
    assert get_model_pricing("").model_id == "claude-sonnet-4-20250514"
    assert get_model_pricing("unknown-model").model_id == "claude-sonnet-4-20250514"
    assert get_model_pricing("sonnet").model_id == "claude-sonnet-4-20250514"
    assert calculate_cost(1_000_000, 1_000_000, model="unknown-model") == Decimal("18.00")
