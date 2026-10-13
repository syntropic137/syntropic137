"""A session's cost split by token type: input, output, cache write, cache read.

The session detail meter shows where the money went by token type. The token
counts and the per-type rates were both in the domain; only the split was not.
These pin the three things the split must never do:

- disagree with the total it splits (the parts must sum to ``total_cost``);
- pass an apportioned harness total off as a rate-table measurement (the
  ``basis`` says which it is);
- report a split that is missing a priced group, or four zeroes standing in
  for "not computed" (it is ``None`` instead).

Rates are read from the table rather than restated as literals: see the module
docstring of ``test_cost_model_resolution.py`` for why a literal rate in a test
is the recurring fault.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    price_session_rows,
)
from syn_shared.agents import ModelId
from syn_shared.pricing import (
    CostSplitBasis,
    TokenTypeCost,
    canonical_cost_usd,
    require_model_pricing,
)

pytestmark = pytest.mark.unit

#: One model-grouped query row. Concretely typed: every column is one of these.
_FakeRow = dict[str, str | int | Decimal | None]
_UNPRICED_REAL_MODEL = "gpt-5.6-mini"


def _group(
    model: str | None,
    *,
    input_tokens: int = 1_000,
    output_tokens: int = 2_000,
    cache_creation: int = 3_000,
    cache_read: int = 40_000,
    sdk_cost: Decimal | None = None,
) -> _FakeRow:
    return {
        "agent_model": model,
        "total_input": input_tokens,
        "total_output": output_tokens,
        "cache_creation": cache_creation,
        "cache_read": cache_read,
        "sdk_cost": sdk_cost,
        "observation_count": 2,
        "execution_id": "exec-1",
        "phase_id": "phase-1",
        "workspace_id": None,
        "started_at": None,
        "last_observation": None,
    }


def _price(*rows: _FakeRow):
    totals = price_session_rows(list(rows), CostCalculator(), "session-1")  # type: ignore[arg-type]  # Mapping stands in for asyncpg.Record
    assert totals is not None
    return totals


def test_rate_table_split_is_each_type_at_its_rate() -> None:
    totals = _price(_group(ModelId.CLAUDE_SONNET_4))
    rates = require_model_pricing(ModelId.CLAUDE_SONNET_4)

    assert totals.cost_by_token_type_basis is CostSplitBasis.RATE_TABLE
    assert (
        totals.cost_by_token_type
        == rates.cost_by_token_type(1_000, 2_000, 3_000, 40_000).canonical()
    )
    assert totals.cost_by_token_type is not None
    assert totals.cost_by_token_type.total == totals.total_cost


def test_two_models_add_up_per_type() -> None:
    totals = _price(
        _group(ModelId.CLAUDE_SONNET_4),
        _group(ModelId.GPT_5_6, input_tokens=500, output_tokens=0, cache_creation=0, cache_read=0),
    )

    assert totals.cost_by_token_type is not None
    assert totals.cost_by_token_type.total == totals.total_cost
    sonnet = require_model_pricing(ModelId.CLAUDE_SONNET_4).cost_by_token_type(
        1_000, 2_000, 3_000, 40_000
    )
    gpt = require_model_pricing(ModelId.GPT_5_6).cost_by_token_type(500, 0, 0, 0)
    assert totals.cost_by_token_type.input_usd == canonical_cost_usd(
        sonnet.input_usd + gpt.input_usd
    )


def test_a_reported_total_is_apportioned_and_labelled() -> None:
    """The harness total is kept; only its split is derived, and it says so."""
    reported = Decimal("0.5")
    totals = _price(_group(ModelId.CLAUDE_SONNET_4, sdk_cost=reported))

    assert totals.total_cost == reported
    assert totals.cost_by_token_type_basis is CostSplitBasis.ALLOCATED
    split = totals.cost_by_token_type
    assert split is not None
    # Within the canonical quantum per part, never more.
    assert abs(split.total - reported) <= Decimal("4e-10")
    rated = require_model_pricing(ModelId.CLAUDE_SONNET_4).cost_by_token_type(
        1_000, 2_000, 3_000, 40_000
    )
    # Same proportions as the rate table.
    assert float(split.cache_read_usd / split.output_usd) == pytest.approx(
        float(rated.cache_read_usd / rated.output_usd)
    )


def test_a_reported_total_with_no_rate_cannot_be_split() -> None:
    """No rate, no proportions: a guessed split would be fiction."""
    totals = _price(_group(_UNPRICED_REAL_MODEL, sdk_cost=Decimal("0.25")))

    assert totals.total_cost == Decimal("0.25")
    assert totals.cost_by_token_type is None
    assert totals.cost_by_token_type_basis is None


def test_one_unsplittable_group_withholds_the_whole_split() -> None:
    """A split missing a priced group would not sum to the total it splits."""
    totals = _price(
        _group(ModelId.CLAUDE_SONNET_4),
        _group(_UNPRICED_REAL_MODEL, sdk_cost=Decimal("0.25")),
    )

    assert totals.cost_by_token_type is None


def test_unpriced_work_is_in_neither_the_total_nor_the_split() -> None:
    totals = _price(_group(ModelId.CLAUDE_SONNET_4), _group(_UNPRICED_REAL_MODEL))

    assert totals.unpriced_observation_count == 2
    assert totals.cost_by_token_type is not None
    assert totals.cost_by_token_type.total == totals.total_cost


def test_token_type_cost_allocation_refuses_without_proportions() -> None:
    assert TokenTypeCost().allocated_to(Decimal("1")) is None
    assert TokenTypeCost().allocated_to(Decimal("0")) == TokenTypeCost()


def test_the_split_round_trips_through_storage() -> None:
    split = TokenTypeCost(
        input_usd=Decimal("0.1"),
        output_usd=Decimal("0.2"),
        cache_creation_usd=Decimal("0.3"),
        cache_read_usd=Decimal("0.4"),
    )
    cost = SessionCost(
        session_id="s",
        cost_by_token_type=split,
        cost_by_token_type_basis=CostSplitBasis.ALLOCATED,
    )

    back = SessionCost.from_dict(cost.to_dict())

    assert back.cost_by_token_type == split
    assert back.cost_by_token_type_basis is CostSplitBasis.ALLOCATED


def test_a_record_without_a_split_reads_back_as_none_not_zero() -> None:
    back = SessionCost.from_dict({"session_id": "s"})

    assert back.cost_by_token_type is None
    assert back.cost_by_token_type_basis is None


def test_calculate_cost_is_the_split_total() -> None:
    """One formula, so the total and its split cannot drift apart."""
    rates = require_model_pricing(ModelId.CLAUDE_SONNET_4)
    assert rates.calculate_cost(7, 11, 13, 17) == rates.cost_by_token_type(7, 11, 13, 17).total
