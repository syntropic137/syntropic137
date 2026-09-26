"""Vendor cost canonicalisation and cache rate multipliers (syn_shared.pricing)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel

from syn_shared.agents import ModelId
from syn_shared.pricing import (
    VENDOR_COST_QUANTUM,
    cache_rate_multipliers,
    canonical_cost_usd,
)

pytestmark = pytest.mark.unit

# The exact values the live v0.30.0-beta.7 API returned for exec-105b88d56234:
# the Claude CLI's JS doubles, stored verbatim in agent_events.
LIVE_PHASE_COST = 0.30566780000000005
LIVE_OTHER_PHASE_COST = 0.13242320000000001


class _CostModel(BaseModel):
    cost: Decimal


def test_live_double_noise_is_removed() -> None:
    assert str(canonical_cost_usd(LIVE_PHASE_COST)) == "0.3056678"


def test_numeric_read_of_the_same_text_is_removed() -> None:
    # What asyncpg hands back for `(data->>'total_cost_usd')::numeric`.
    assert str(canonical_cost_usd(Decimal("0.30566780000000005"))) == "0.3056678"


def test_summed_noisy_values_come_out_exact() -> None:
    # A SQL SUM over the stored text keeps both noise tails.
    summed = Decimal("0.30566780000000005") + Decimal("0.13242320000000001")
    assert str(summed) == "0.43809100000000006"
    assert str(canonical_cost_usd(summed)) == "0.438091"
    # Per row then sum agrees.
    per_row = canonical_cost_usd(LIVE_PHASE_COST) + canonical_cost_usd(LIVE_OTHER_PHASE_COST)
    # Exact in value; Decimal addition keeps the operands' exponent, so a
    # Python-side sum is re-canonicalised before it is reported.
    assert per_row == Decimal("0.438091")
    assert str(canonical_cost_usd(per_row)) == "0.438091"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (100, "100"),
        (Decimal("100.000"), "100"),
        (100.0, "100"),
        (Decimal("1E+2"), "100"),
        (0, "0"),
        (0.0, "0"),
        (Decimal("0E-10"), "0"),
        (Decimal("-0.0"), "0"),
        ("2.5", "2.5"),
        (Decimal("0.00000000004"), "0"),
        (Decimal("0.00000000006"), "1E-10"),
        (-0.30566780000000005, "-0.3056678"),
    ],
)
def test_canonical_form_has_no_exponent_or_trailing_zeros(raw: object, expected: str) -> None:
    result = canonical_cost_usd(raw)  # type: ignore[arg-type]  # parametrized over the accepted union
    if expected == "1E-10":
        # The smallest non-zero value is exactly one quantum; compare by value.
        # str() of any Decimal under 1e-6 is scientific (Python's rule, not
        # ours), so this case serializes as "1E-10"; see canonical_cost_usd.
        assert result == VENDOR_COST_QUANTUM
        assert "E" not in format(result, "f")
        return
    assert str(result) == expected
    assert "E" not in str(result)


def test_pydantic_serializes_the_canonical_form() -> None:
    dumped = _CostModel(cost=canonical_cost_usd(100)).model_dump_json()
    assert dumped == '{"cost":"100"}'
    dumped_zero = _CostModel(cost=canonical_cost_usd(0)).model_dump_json()
    assert dumped_zero == '{"cost":"0"}'


def test_none_stays_none() -> None:
    assert canonical_cost_usd(None) is None


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), Decimal("NaN")])
def test_non_finite_is_rejected(raw: float | Decimal) -> None:
    with pytest.raises(ValueError, match="finite"):
        canonical_cost_usd(raw)


def test_quantum_is_far_below_the_cheapest_token() -> None:
    from syn_shared.pricing import MODEL_PRICING_TABLE

    cheapest_per_token = min(
        min(
            p.input_per_million,
            p.output_per_million,
            p.cache_read_per_million,
            p.cache_creation_per_million,
        )
        for p in MODEL_PRICING_TABLE.values()
    ) / Decimal(1_000_000)
    assert cheapest_per_token >= VENDOR_COST_QUANTUM * 100


def test_opus_5_5_only() -> None:
    rates = cache_rate_multipliers([ModelId.CLAUDE_OPUS_5_5])
    assert rates.cache_read == Decimal("0.05")
    assert rates.cache_write == Decimal("1.25")


def test_opus_5_5_and_gpt_6_sol_disagree_on_read_only() -> None:
    rates = cache_rate_multipliers([ModelId.CLAUDE_OPUS_5_5, ModelId.GPT_6_SOL])
    assert rates.cache_read is None
    assert rates.cache_write == Decimal("1.25")


def test_unknown_model_has_no_multiplier() -> None:
    rates = cache_rate_multipliers(["not-a-real-model"])
    assert rates.cache_read is None
    assert rates.cache_write is None


def test_unknown_beside_known_has_no_multiplier() -> None:
    rates = cache_rate_multipliers([ModelId.CLAUDE_OPUS_5_5, "not-a-real-model"])
    assert rates.cache_read is None
    assert rates.cache_write is None


def test_no_models_has_no_multiplier() -> None:
    rates = cache_rate_multipliers([])
    assert rates.cache_read is None
    assert rates.cache_write is None


def test_json_number_of_the_live_double_is_clean() -> None:
    import json

    from syn_shared.pricing import cost_json_number

    assert json.dumps(cost_json_number(LIVE_PHASE_COST)) == "0.3056678"
    assert json.dumps(cost_json_number(Decimal("0.004936000"))) == "0.004936"
    assert json.dumps(cost_json_number(Decimal("12345.1234567891"))) == "12345.1234567891"
