"""Tests for GPT-5.6 pricing resolution."""

from decimal import Decimal

import pytest

from syn_shared.agents import ModelId
from syn_shared.pricing import (
    PricedAmount,
    PricingStatus,
    UnknownModelPricingError,
    calculate_cost,
    price_tokens,
    require_model_pricing,
    resolve_model_pricing,
)

# Marked at module scope: this file was never COLLECTED before the
# testpaths change in this commit, so nothing here had a reason to carry a
# marker. Unmarked now means collected but run by no CI job.
pytestmark = pytest.mark.unit


def test_gpt_5_6_resolves_to_codex_pricing() -> None:
    """`gpt-5.6` is OpenAI's alias for `gpt-5.6-sol` and carries Sol's rates.

    The literals here previously asserted $5.00/$30.00/$0.50, which matched no
    published OpenAI tier. This test therefore held the wrong rate in place: it
    passed precisely because implementation and expectation shared one mistake.
    The authoritative field-by-field assertions now live in
    ``tests/test_openai_published_rates.py``, transcribed from the vendor page,
    so this case only needs to establish that the alias resolves at all.
    """
    pricing = resolve_model_pricing("gpt-5.6")

    assert pricing is not None
    assert pricing.model_id == "gpt-5.6"
    assert pricing.input_per_million == Decimal("4.00")
    assert pricing.output_per_million == Decimal("20.00")
    assert pricing.cache_read_per_million == Decimal("0.40")


def test_gpt_5_6_alias_and_sol_agree() -> None:
    """The alias must never drift from the model it points at."""
    alias = resolve_model_pricing("gpt-5.6")
    sol = resolve_model_pricing("gpt-5.6-sol")
    assert alias is not None and sol is not None
    assert alias.input_per_million == sol.input_per_million
    assert alias.output_per_million == sol.output_per_million
    assert alias.cache_read_per_million == sol.cache_read_per_million


def test_priced_amount_rejects_contradictory_states() -> None:
    """A cost may not lie about its own provenance (cross-model review, #816)."""
    for bad_status in (PricingStatus.PRICED, PricingStatus.PLACEHOLDER):
        with pytest.raises(ValueError):
            PricedAmount(cost=None, status=bad_status)
    for bad_status in (
        PricingStatus.UNPRICED_UNKNOWN_MODEL,
        PricingStatus.UNPRICED_NO_RATE,
    ):
        with pytest.raises(ValueError):
            PricedAmount(cost=Decimal("1"), status=bad_status)


def test_zero_token_priced_run_is_still_priced() -> None:
    """A known model that used no tokens costs 0 - priced, not unpriced."""
    amount = price_tokens("opus", 0, 0)
    assert amount.cost == Decimal("0")
    assert amount.status is PricingStatus.PRICED
    assert amount.is_priced


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


def test_all_current_rates_are_verified_not_placeholder() -> None:
    """No shipped rate is a guess. PLACEHOLDER exists for when one is."""
    for model in ("gpt-5.6", "gpt-5.6-sol", "opus", "sonnet", "haiku"):
        assert price_tokens(model, 1_000_000, 0).status is PricingStatus.PRICED, model


def test_priced_amount_costs_match_the_table() -> None:
    priced = price_tokens("opus", 1_000_000, 1_000_000)
    assert priced.status is PricingStatus.PRICED
    assert priced.model == ModelId.CLAUDE_OPUS_5
    # Opus 5: $5/M input + $25/M output
    assert priced.cost == Decimal("30.00")
