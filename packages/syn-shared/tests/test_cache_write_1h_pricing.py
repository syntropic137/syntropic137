"""Pricing a 1-hour cache write (#2145 slice A).

A 1-hour cache write is billed at 2x the base input rate on every Claude row,
not at the 5-minute (1.25x) rate. Nothing feeds the count yet (slice B), so the
default of 0 must leave every existing cost byte-identical.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_shared.agents import ModelId
from syn_shared.pricing import (
    MODEL_PRICING_TABLE,
    ModelPricing,
    TokenTypeCost,
    calculate_cost,
)

pytestmark = pytest.mark.unit

_MILLION = 1_000_000
_OPUS_5_5 = MODEL_PRICING_TABLE[ModelId.CLAUDE_OPUS_5_5]

# Every row that is not an Anthropic model: OpenAI has no 1-hour cache write.
_NON_ANTHROPIC = frozenset(m for m in MODEL_PRICING_TABLE if not m.value.startswith("claude-"))


def test_opus_5_5_prices_a_1h_write_at_2x_input_not_the_5min_rate() -> None:
    split = _OPUS_5_5.cost_by_token_type(0, 0, cache_creation_1h=_MILLION)

    assert split.cache_creation_usd == Decimal("8.00")
    assert split.total == Decimal("8.00")
    assert _OPUS_5_5.calculate_cost(0, 0, cache_creation_1h=_MILLION) == Decimal("8.00")
    assert calculate_cost(
        0, 0, str(ModelId.CLAUDE_OPUS_5_5), cache_creation_1h=_MILLION
    ) == Decimal("8.00")


def test_1h_and_5min_writes_are_priced_each_at_its_own_rate() -> None:
    split = _OPUS_5_5.cost_by_token_type(0, 0, cache_creation=_MILLION, cache_creation_1h=_MILLION)

    # $5.00 (5-min) + $8.00 (1-hour), both carried in cache_creation_usd.
    assert split.cache_creation_usd == Decimal("13.00")
    assert split.total == Decimal("13.00")


@pytest.mark.parametrize("model", sorted(set(MODEL_PRICING_TABLE) - _NON_ANTHROPIC), ids=str)
def test_every_claude_row_writes_1h_at_2x_input(model: ModelId) -> None:
    pricing = MODEL_PRICING_TABLE[model]
    assert pricing.cache_creation_1h_per_million == 2 * pricing.input_per_million


@pytest.mark.parametrize("model", sorted(_NON_ANTHROPIC), ids=str)
def test_non_anthropic_rows_price_a_1h_write_as_their_cache_write(model: ModelId) -> None:
    pricing = MODEL_PRICING_TABLE[model]
    assert pricing.cache_creation_1h_per_million == pricing.cache_creation_per_million


def test_the_non_anthropic_set_is_the_openai_rows() -> None:
    # Guards the classifier above: a Claude id that stopped matching "claude-"
    # would silently move its row to the weaker rule.
    openai_rows = {
        ModelId.GPT_6_1_SOL,
        ModelId.GPT_6_SOL,
        ModelId.GPT_6_LUNA,
        ModelId.GPT_5_6_SOL,
        ModelId.GPT_5_6_TERRA,
        ModelId.GPT_5_6_LUNA,
        ModelId.GPT_5_6,
    }
    assert openai_rows == _NON_ANTHROPIC


def _legacy_split(pricing: ModelPricing, i: int, o: int, cw: int, cr: int) -> TokenTypeCost:
    """The split as computed before 1-hour writes existed, from the same rates."""
    m = Decimal(_MILLION)
    return TokenTypeCost(
        input_usd=Decimal(i) * pricing.input_per_million / m,
        output_usd=Decimal(o) * pricing.output_per_million / m,
        cache_creation_usd=Decimal(cw) * pricing.cache_creation_per_million / m,
        cache_read_usd=Decimal(cr) * pricing.cache_read_per_million / m,
    )


@pytest.mark.parametrize("model", sorted(MODEL_PRICING_TABLE), ids=str)
def test_default_zero_1h_leaves_every_row_byte_identical(model: ModelId) -> None:
    pricing = MODEL_PRICING_TABLE[model]
    counts = (123_457, 9_871, 54_321, 1_234_567)

    split = pricing.cost_by_token_type(*counts)
    legacy = _legacy_split(pricing, *counts)

    assert split == legacy
    # str() compares the exponent too, so 1.50 vs 1.5 would fail here.
    assert str(split.cache_creation_usd) == str(legacy.cache_creation_usd)
    assert str(split.total) == str(legacy.total)
    assert str(pricing.calculate_cost(*counts)) == str(legacy.total)
    assert str(pricing.calculate_cost(*counts, cache_creation_1h=0)) == str(legacy.total)


def test_total_includes_the_1h_write() -> None:
    split = _OPUS_5_5.cost_by_token_type(1_000, 1_000, cache_creation_1h=1_000)
    assert split.total == Decimal("0.004") + Decimal("0.02") + Decimal("0.008")


def test_add_carries_the_1h_write() -> None:
    a = _OPUS_5_5.cost_by_token_type(0, 0, cache_creation_1h=_MILLION)
    b = _OPUS_5_5.cost_by_token_type(0, 0, cache_creation=_MILLION)
    assert (a + b).cache_creation_usd == Decimal("13.00")
    assert (a + b).total == Decimal("13.00")


def test_allocated_to_apportions_the_1h_write() -> None:
    # $4 input + $8 1-hour write: a $6 reported total splits 2:4.
    split = _OPUS_5_5.cost_by_token_type(_MILLION, 0, cache_creation_1h=_MILLION)
    allocated = split.allocated_to(Decimal("6"))

    assert allocated is not None
    assert allocated.input_usd == Decimal("2")
    assert allocated.cache_creation_usd == Decimal("4")
    assert allocated.total == Decimal("6")


def test_canonical_keeps_the_1h_write() -> None:
    split = _OPUS_5_5.cost_by_token_type(0, 0, cache_creation_1h=3).canonical()
    # 3 tokens x $8/MTok = 0.000024, well above the 1e-10 quantum.
    assert split.cache_creation_usd == Decimal("0.000024")
    assert split.total == Decimal("0.000024")
