"""Pin OpenAI rates to the published table, field by field.

WHY THIS EXISTS. The gpt-5.6 rates have been wrong twice. First as an
unverified ``TODO(#780)`` placeholder at $15/$60/$1.50. Then, after a review
that recorded "verified against the OpenAI pricing page and the OpenRouter
models API", at $5.00/$30.00/$0.50/$6.25 - which matches NEITHER published
context tier, but IS an exact match for OpenAI's `chat-latest` ($5.00 input /
$0.50 cached input / $30.00 output). Sol is described in the pricing table as
the model a ChatGPT-account codex login runs, so the likely error was pricing
the ChatGPT product instead of the API model.

Both times the wrong value shipped behind a claim of verification, and no test
disagreed, because every existing pricing test asserted only that a model
RESOLVES and that its rates are positive. Those properties hold just as well
for a wrong number.

So this file asserts the actual published figures. It is deliberately literal:
the numbers are transcribed from the vendor page and a diff here is meant to be
read against that page, not reasoned about from the surrounding code.

Source: https://developers.openai.com/api/docs/pricing (read 2026-08-26).

TWO DIMENSIONS THIS TABLE CANNOT EXPRESS.

Context tier: short and long. Input, cached input and cache write scale 2x;
output scales 1.5x. Not a uniform multiplier.
Service tier: Standard, Batch, Flex and Fast mode. Sol short-context output
spans $10.00 (Batch/Flex) to $40.00 (Fast).

Together that is an 8x spread on a single model, and ``ModelPricing`` holds one
number. Standard plus short context is asserted here: standard because codex
does not set ``service_tier``, short because observed sessions on this platform
run 897 to roughly 28k input tokens. If tiering lands, this file should grow
cases rather than have these numbers edited.

Sol's rates are also PROMOTIONAL, stated as available at least through
2026-11-21. They have a known expiry.
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

    def test_rate_is_not_chat_latest(
        self, model: str, published: tuple[str, str, str, str]
    ) -> None:
        """Guard the specific wrong rate that shipped: OpenAI's ChatGPT model.

        The 2026-08-16 "verified" values were $5.00 input / $0.50 cached input
        / $30.00 output, which is `chat-latest` in the Specialized models table
        exactly. The entry's comment describes Sol as the model a ChatGPT-account
        codex login runs, so pricing the ChatGPT product rather than the API
        model is the plausible and repeatable mistake. It is repeatable because
        the confusion is in the naming, not in anyone's care.
        """
        pricing = resolve_model_pricing(model)
        assert pricing is not None

        chat_latest = (Decimal("5.00"), Decimal("0.50"), Decimal("30.00"))
        actual = (
            pricing.input_per_million,
            pricing.cache_read_per_million,
            pricing.output_per_million,
        )
        assert actual != chat_latest, (
            f"{model} carries chat-latest's rates. chat-latest is the ChatGPT "
            f"model, not the gpt-5.6 API model. Use the Flagship models table."
        )


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
class TestLongContextTierRelationships:
    """Pin the recorded long-context tier, field by field.

    The first version of this class asserted "2x on every field" and read only
    tuple index 0, so nine of the twelve long-context literals were never
    consumed by any assertion and the class name stated something false: output
    scales 1.5x, not 2x, while input, cached input and cache write scale 2x.

    That is the same defect this whole file exists to catch, one level up. A
    test that transcribes numbers into a fixture and then checks one of them is
    not pinning the fixture, it is decorating it. Every literal below is now
    consumed by an assertion that can fail.
    """

    #: field index -> (name, long/short ratio) as published.
    RATIOS: tuple[tuple[int, str, str], ...] = (
        (0, "input", "2"),
        (1, "cached input", "2"),
        (2, "cache write", "2"),
        (3, "output", "1.5"),
    )

    @pytest.mark.parametrize("model", sorted(PUBLISHED_SHORT_CONTEXT))
    @pytest.mark.parametrize(("index", "field", "ratio"), RATIOS)
    def test_long_tier_scales_by_published_ratio(
        self, model: str, index: int, field: str, ratio: str
    ) -> None:
        short = Decimal(PUBLISHED_SHORT_CONTEXT[model][index])
        long_ = Decimal(PUBLISHED_LONG_CONTEXT[model][index])
        assert long_ == short * Decimal(ratio), (
            f"{model} {field}: published long tier is {long_}, expected {short} * {ratio}"
        )

    @pytest.mark.parametrize("model", sorted(PUBLISHED_SHORT_CONTEXT))
    def test_output_does_not_scale_like_the_other_fields(self, model: str) -> None:
        """Guard the specific wrong belief that shipped here.

        If someone reasons "long context is just double" and edits the output
        literal to match, this fails.
        """
        short_out = Decimal(PUBLISHED_SHORT_CONTEXT[model][3])
        long_out = Decimal(PUBLISHED_LONG_CONTEXT[model][3])
        assert long_out != short_out * 2, f"{model} long-context output must be 1.5x short, not 2x"

    @pytest.mark.parametrize("model", sorted(PUBLISHED_SHORT_CONTEXT))
    def test_untiered_table_uses_the_short_tier(self, model: str) -> None:
        """Make the deliberate choice visible: we price short, not long."""
        pricing = resolve_model_pricing(model)
        assert pricing is not None
        assert pricing.input_per_million == Decimal(PUBLISHED_SHORT_CONTEXT[model][0])
        assert pricing.input_per_million != Decimal(PUBLISHED_LONG_CONTEXT[model][0])
