"""Tests for model-aware session cost calculation.

Every test here MUST carry ``@pytest.mark.unit``. CI runs ``pytest -m unit``,
so an unmarked test in this file is collected by a bare ``pytest`` run and by
nothing else - it can fail on main indefinitely without turning a check red.
That is exactly what happened: both ``gpt-5.6`` cases below still asserted the
pre-#816 rates ($15/$60) after that PR corrected them to $5/$30, and stayed
red on main because no CI job ran them.

It then happened AGAIN. The $5/$30 those cases were updated to was itself
wrong, so this file carried a third incorrect literal. Duplicating a rate into
a test expectation is the recurring fault, not any one number: the assertion
looks like verification while only restating the implementation. Rates are now
pinned field by field against the vendor page in
``packages/syn-shared/tests/test_openai_published_rates.py``; cases here should
assert that pricing is MODEL-AWARE, not what any particular rate is.
"""

from collections.abc import Mapping
from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import (
    SessionCostProjection,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.test_projection import (
    MockProjectionStore,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    price_session_rows,
)
from syn_shared.agents import ModelId

# Matches the convention in the sibling test_query_service.py: a query row is a
# read-only mapping here, since these cases exercise the pricing merge rather
# than asyncpg itself.
_FakeRow = Mapping[str, object]

# A real OpenAI model with no rate in MODEL_PRICING_TABLE - the production shape
# of "unpriced", rather than an invented id that could never occur on the wire.
_UNPRICED_REAL_MODEL = "gpt-5.6-mini"


def _token_usage_group(
    model: str | None,
    *,
    input_tokens: int,
    output_tokens: int,
    observation_count: int = 3,
) -> _FakeRow:
    """One model-grouped token_usage row, in the shape the SQL now returns."""
    return {
        "agent_model": model,
        "total_input": input_tokens,
        "total_output": output_tokens,
        "cache_creation": 0,
        "cache_read": 0,
        "observation_count": observation_count,
        "execution_id": "exec-1",
        "phase_id": "phase-1",
        "workspace_id": None,
        "started_at": None,
        "last_observation": None,
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model", "expected"),
    [
        # 1M in + 1M out. gpt-5.6 aliases gpt-5.6-sol, standard tier / short
        # context: $4.00 in + $20.00 out. This literal has now been wrong three
        # times ($15/$60, then $5/$30); see tests/test_openai_published_rates.py,
        # which pins every field to the vendor page so this one does not have to.
        (ModelId.GPT_5_6, Decimal("24.00")),
        (ModelId.CLAUDE_SONNET_4, Decimal("18.00")),
    ],
)
@pytest.mark.asyncio
async def test_projection_prices_token_usage_by_model(model: str, expected: Decimal) -> None:
    store = MockProjectionStore()
    projection = SessionCostProjection(store)

    await projection.on_agent_observation(
        {
            "session_id": f"session-{model}",
            "event_type": ObservationType.TOKEN_USAGE.value,
            "data": {
                "input_tokens": 1_000_000,
                "output_tokens": 1_000_000,
                "model": model,
            },
        }
    )

    session_cost = await projection.get_session_cost(f"session-{model}")
    assert session_cost is not None
    assert session_cost.total_cost_usd == expected
    assert session_cost.cost_by_model == {model: expected}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (ModelId.GPT_5_6, Decimal("24.00")),
        (ModelId.CLAUDE_SONNET_4, Decimal("18.00")),
    ],
)
def test_session_pricing_uses_resolved_model(model: str, expected: Decimal) -> None:
    totals = price_session_rows(
        [_token_usage_group(model, input_tokens=1_000_000, output_tokens=1_000_000)],
        CostCalculator(),
        "session-1",
    )

    assert totals is not None
    assert totals.total_cost == expected
    assert totals.unpriced_observation_count == 0


@pytest.mark.unit
def test_session_pricing_reports_unpriced_rather_than_zero() -> None:
    """A model with no rate must not come back as a priceable zero (#890)."""
    totals = price_session_rows(
        [_token_usage_group(_UNPRICED_REAL_MODEL, input_tokens=1_000_000, output_tokens=1_000_000)],
        CostCalculator(),
        "session-1",
    )

    assert totals is not None
    assert totals.total_cost == Decimal("0")
    assert totals.unpriced_observation_count == 3
    assert totals.cost_by_model == {}


@pytest.mark.unit
class TestMixedModelSession:
    """A session is one agent but not necessarily one model (#788, #890).

    The old shape summed the whole session into one row and took
    ``MAX(data->>'model')``, then priced everything at that single model. These
    cases pin both halves of the resulting lie: the priced work must keep its
    real cost, and the unpriced work must be COUNTED rather than billed at
    somebody else's rate.
    """

    def test_priced_and_unpriced_groups_both_report(self) -> None:
        totals = price_session_rows(
            [
                _token_usage_group(
                    ModelId.CLAUDE_SONNET_4,
                    input_tokens=1_000_000,
                    output_tokens=1_000_000,
                    observation_count=5,
                ),
                _token_usage_group(
                    _UNPRICED_REAL_MODEL,
                    input_tokens=2_000_000,
                    output_tokens=2_000_000,
                    observation_count=9,
                ),
            ],
            CostCalculator(),
            "session-mixed",
        )

        assert totals is not None
        # Sonnet 4: $3 in + $15 out over 1M each.
        assert totals.total_cost == Decimal("18.00")
        # ONLY the unpriced group contributes to the count. Counting the priced
        # group too would make every mixed session look entirely unmeasured.
        assert totals.unpriced_observation_count == 9
        # Tokens from BOTH groups are real and must be reported.
        assert totals.input_tokens == 3_000_000
        assert totals.output_tokens == 3_000_000
        # The unpriced model must not appear in the breakdown claiming a cost.
        assert totals.cost_by_model == {ModelId.CLAUDE_SONNET_4: Decimal("18.00")}

    def test_unknown_model_is_not_billed_at_the_other_group_rate(self) -> None:
        """The specific pre-fix failure: MAX(model) picked one rate for both."""
        totals = price_session_rows(
            [
                _token_usage_group(
                    ModelId.CLAUDE_SONNET_4, input_tokens=1_000_000, output_tokens=1_000_000
                ),
                _token_usage_group(None, input_tokens=1_000_000, output_tokens=1_000_000),
            ],
            CostCalculator(),
            "session-mixed",
        )

        assert totals is not None
        # If the null-model group were priced as Sonnet the total would be $36.
        assert totals.total_cost == Decimal("18.00")
        assert totals.unpriced_observation_count == 3

    def test_primary_model_is_the_one_that_did_the_work(self) -> None:
        """``agent_model`` is one field, so the dominant model wins - not MAX()."""
        totals = price_session_rows(
            [
                _token_usage_group(ModelId.CLAUDE_SONNET_4, input_tokens=10, output_tokens=10),
                _token_usage_group(
                    ModelId.CLAUDE_HAIKU_3_5, input_tokens=1_000_000, output_tokens=1_000_000
                ),
            ],
            CostCalculator(),
            "session-mixed",
        )

        assert totals is not None
        assert totals.primary_model == ModelId.CLAUDE_HAIKU_3_5


@pytest.mark.unit
def test_zero_token_observation_is_a_priced_zero_not_unpriced() -> None:
    """Zero tokens cost zero at every rate, so no model is needed to say so (#890).

    Resolving the model first made a no-token observation with no model report
    as unpriced - claiming we cannot say what it cost, when we can say exactly.
    """
    totals = price_session_rows(
        [_token_usage_group(None, input_tokens=0, output_tokens=0)],
        CostCalculator(),
        "session-empty",
    )

    assert totals is not None
    assert totals.total_cost == Decimal("0")
    assert totals.unpriced_observation_count == 0
