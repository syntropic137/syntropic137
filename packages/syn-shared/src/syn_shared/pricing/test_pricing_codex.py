"""Tests for GPT-5.6 pricing resolution."""

from decimal import Decimal

import pytest

from syn_shared.agents import ModelId
from syn_shared.pricing import (
    PricingStatus,
    UnknownModelPricingError,
    calculate_cost,
    price_tokens,
    require_model_pricing,
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


# ADR-067 D4: these previously asserted that an unknown model, and the empty
# string, resolve to Sonnet 4 pricing. That fallback is what let unknown models
# be priced confidently and wrongly, so the assertions are inverted: nothing
# substitutes a model any more.


def test_unknown_model_is_never_substituted() -> None:
    for unknown in ("", "unknown-model", "claude-sonnet-4-20991231"):
        assert resolve_model_pricing(unknown) is None, unknown
        with pytest.raises(UnknownModelPricingError):
            require_model_pricing(unknown)
        with pytest.raises(UnknownModelPricingError):
            calculate_cost(1_000_000, 1_000_000, model=unknown)


def test_aliases_track_the_current_generation() -> None:
    assert require_model_pricing("sonnet").model_id == ModelId.CLAUDE_SONNET_5
    assert require_model_pricing("opus").model_id == ModelId.CLAUDE_OPUS_5
    assert require_model_pricing("haiku").model_id == ModelId.CLAUDE_HAIKU_4_5


def test_price_tokens_reports_unpriced_rather_than_zero() -> None:
    missing_model = price_tokens(None, 1_000, 1_000)
    assert missing_model.cost is None
    assert missing_model.status is PricingStatus.UNPRICED_UNKNOWN_MODEL
    assert not missing_model.is_priced

    unknown_rate = price_tokens("unknown-model", 1_000, 1_000)
    assert unknown_rate.cost is None
    assert unknown_rate.status is PricingStatus.UNPRICED_NO_RATE
    assert unknown_rate.model == "unknown-model"


def test_price_tokens_flags_unverified_rates_as_placeholder() -> None:
    # gpt-5.6 rates are TODO(#780) placeholders; gpt-5.6-sol was verified.
    assert price_tokens("gpt-5.6", 1_000_000, 0).status is PricingStatus.PLACEHOLDER
    assert price_tokens("gpt-5.6-sol", 1_000_000, 0).status is PricingStatus.PRICED


def test_priced_amount_costs_match_the_table() -> None:
    priced = price_tokens("opus", 1_000_000, 1_000_000)
    assert priced.status is PricingStatus.PRICED
    assert priced.model == ModelId.CLAUDE_OPUS_5
    # Opus 5: $5/M input + $25/M output
    assert priced.cost == Decimal("30.00")
