"""#2145 slice B1: ``price_tokens``, the production cost entry point, prices 1-hour writes.

Slice A taught ``ModelPricing`` the 1-hour rate; this pins that the one entry
point production code is told to use passes the count through to it.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest

from syn_shared.agents import ModelId
from syn_shared.pricing import PricingStatus, price_tokens

pytestmark = pytest.mark.unit

_MILLION = 1_000_000
_OPUS_5_5 = ModelId.CLAUDE_OPUS_5_5.value


def test_price_tokens_prices_a_1h_write_at_the_1h_rate() -> None:
    priced = price_tokens(_OPUS_5_5, 0, 0, cache_creation_1h=_MILLION)

    assert priced.cost == Decimal("8.00")


def test_price_tokens_prices_each_cache_tier_at_its_own_rate() -> None:
    priced = price_tokens(_OPUS_5_5, 0, 0, cache_creation=_MILLION, cache_creation_1h=_MILLION)

    assert priced.cost == Decimal("13.00")


def test_a_1h_only_turn_with_no_model_is_unpriced_not_zero() -> None:
    """The zero short-circuit must not swallow a turn whose only spend is 1-hour writes."""
    priced = price_tokens(None, 0, 0, cache_creation_1h=_MILLION)

    assert priced.cost is None
    assert priced.status is PricingStatus.UNPRICED_UNKNOWN_MODEL


def test_the_unpriced_warning_names_the_1h_count(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="syn_shared.pricing"):
        price_tokens("no-such-model", 0, 0, cache_creation_1h=4242)

    assert "cache_creation_1h=4242" in caplog.text
