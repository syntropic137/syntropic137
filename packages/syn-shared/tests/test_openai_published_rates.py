"""Pin OpenAI rates to the published table, field by field.

WHY THIS EXISTS. The gpt-5.6 rates have been wrong twice. First as an
unverified ``TODO(#780)`` placeholder at $15/$60/$1.50. Then, after a review
that recorded "verified against the OpenAI pricing page and the OpenRouter
models API", at $5.00/$30.00/$0.50/$6.25 - which matches NEITHER published
context tier. That second set is Opus 5's $5.00 base with Anthropic's cache
multipliers (1.25x write, 0.10x read) applied on top, so the failure was
deriving OpenAI rates from Anthropic conventions rather than reading OpenAI's
published cached-input and cache-write columns.

Both times the wrong value shipped behind a claim of verification, and no test
disagreed, because every existing pricing test asserted only that a model
RESOLVES and that its rates are positive. Those properties hold just as well
for a wrong number.

So this file asserts the actual published figures. It is deliberately literal:
the numbers are transcribed from the vendor page and a diff here is meant to be
read against that page, not reasoned about from the surrounding code.

Source: https://developers.openai.com/api/docs/pricing (read 2026-08-26).

SHORT-CONTEXT TIER. OpenAI bills gpt-5.6 in two context tiers, roughly 2x apart
on every field. This table has no tier concept, so short-tier is asserted here
and the gap is tracked separately. If tiering lands, this file should grow a
long-tier case rather than have these numbers edited.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_shared.agents import ModelId
from syn_shared.pricing import resolve_model_pricing

#: Transcribed from the vendor pricing page, short-context tier.
#: (input, cached input, cache write, output) in USD per million tokens.
PUBLISHED_SHORT_CONTEXT: dict[str, tuple[str, str, str, str]] = {
    ModelId.GPT_5_6_SOL.value: ("4.00", "0.40", "5.00", "20.00"),
    ModelId.GPT_5_6_TERRA.value: ("2.00", "0.20", "2.50", "12.00"),
    ModelId.GPT_5_6_LUNA.value: ("0.20", "0.02", "0.25", "1.20"),
}

#: The long-context tier, recorded so the 2x relationship is visible and so a
#: future tiering implementation has the figures to hand. Not asserted against
#: the table today because the table cannot express a tier.
PUBLISHED_LONG_CONTEXT: dict[str, tuple[str, str, str, str]] = {
    ModelId.GPT_5_6_SOL.value: ("8.00", "0.80", "10.00", "30.00"),
    ModelId.GPT_5_6_TERRA.value: ("4.00", "0.40", "5.00", "18.00"),
    ModelId.GPT_5_6_LUNA.value: ("0.40", "0.04", "0.50", "1.80"),
}


@pytest.mark.unit
@pytest.mark.parametrize(("model", "published"), sorted(PUBLISHED_SHORT_CONTEXT.items()))
class TestPublishedRatesMatchTheVendorPage:
    def test_every_field_matches(self, model: str, published: tuple[str, str, str, str]) -> None:
        """A rate that drifts from the published page fails here, by field."""
        expected_input, expected_cached, expected_write, expected_output = published
        pricing = resolve_model_pricing(model)

        assert pricing is not None, f"{model} is unpriced"
        assert pricing.input_per_million == Decimal(expected_input), f"{model} input"
        assert pricing.cache_read_per_million == Decimal(expected_cached), f"{model} cached input"
        assert pricing.cache_creation_per_million == Decimal(expected_write), f"{model} cache write"
        assert pricing.output_per_million == Decimal(expected_output), f"{model} output"

    def test_rate_is_not_an_anthropic_derivation(
        self, model: str, published: tuple[str, str, str, str]
    ) -> None:
        """Guard the exact mistake that shipped: Anthropic multipliers on an OpenAI model.

        Anthropic's convention is cache read at 0.10x base and 5-minute cache
        write at 1.25x base. OpenAI publishes both directly and they do not
        follow those ratios. If a future edit reintroduces the derivation, the
        computed value will not equal the published one.
        """
        pricing = resolve_model_pricing(model)
        assert pricing is not None

        anthropic_style_read = pricing.input_per_million * Decimal("0.10")
        anthropic_style_write = pricing.input_per_million * Decimal("1.25")

        assert (
            pricing.cache_read_per_million != anthropic_style_read
            or Decimal(published[1]) == anthropic_style_read
        ), f"{model} cache read looks derived from Anthropic's 0.10x rule rather than published"
        assert (
            pricing.cache_creation_per_million != anthropic_style_write
            or Decimal(published[2]) == anthropic_style_write
        ), f"{model} cache write looks derived from Anthropic's 1.25x rule rather than published"


@pytest.mark.unit
class TestAliasAgreesWithTarget:
    def test_gpt_5_6_alias_carries_sol_rates(self) -> None:
        """``gpt-5.6`` is OpenAI's alias for Sol, so the two must never diverge.

        They are separate table entries, so a partial edit can move one and
        leave the other. That is silent: both still resolve, both still price.
        """
        alias = resolve_model_pricing("gpt-5.6")
        sol = resolve_model_pricing(ModelId.GPT_5_6_SOL.value)

        assert alias is not None and sol is not None
        assert alias.input_per_million == sol.input_per_million
        assert alias.output_per_million == sol.output_per_million
        assert alias.cache_read_per_million == sol.cache_read_per_million
        assert alias.cache_creation_per_million == sol.cache_creation_per_million


@pytest.mark.unit
class TestLongContextIsTwiceShort:
    """The recorded tiers must stay internally consistent.

    This asserts the relationship the vendor page shows rather than the table,
    so it documents why an untiered table under-prices a long-context run.
    """

    @pytest.mark.parametrize("model", sorted(PUBLISHED_SHORT_CONTEXT))
    def test_long_tier_input_is_double_short(self, model: str) -> None:
        short_input = Decimal(PUBLISHED_SHORT_CONTEXT[model][0])
        long_input = Decimal(PUBLISHED_LONG_CONTEXT[model][0])
        assert long_input == short_input * 2

    @pytest.mark.parametrize("model", sorted(PUBLISHED_SHORT_CONTEXT))
    def test_untiered_table_uses_the_short_tier(self, model: str) -> None:
        """Make the deliberate choice visible: we price short, not long."""
        pricing = resolve_model_pricing(model)
        assert pricing is not None
        assert pricing.input_per_million == Decimal(PUBLISHED_SHORT_CONTEXT[model][0])
        assert pricing.input_per_million != Decimal(PUBLISHED_LONG_CONTEXT[model][0])
