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

from decimal import Decimal
from unittest.mock import Mock

import pytest

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import (
    SessionCostProjection,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.test_projection import (
    MockProjectionStore,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    TimescaleSessionCostQuery,
)
from syn_shared.agents import ModelId


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
        # 1M in + 1M out. gpt-5.6 aliases gpt-5.6-sol, standard tier / short
        # context: $4.00 in + $20.00 out. This literal has now been wrong three
        # times ($15/$60, then $5/$30); see tests/test_openai_published_rates.py,
        # which pins every field to the vendor page so this one does not have to.
        (ModelId.GPT_5_6, Decimal("24.00")),
        (ModelId.CLAUDE_SONNET_4, Decimal("18.00")),
    ],
)
def test_timescale_cost_calculation_uses_resolved_model(model: str, expected: Decimal) -> None:
    query = TimescaleSessionCostQuery(Mock())

    priced = query._calculate_cost(
        session_id="session-1",
        exec_result=None,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation=0,
        cache_read=0,
        agent_model=model,
    )

    assert priced.cost == expected
    assert priced.is_priced


@pytest.mark.unit
def test_timescale_cost_calculation_reports_unpriced_rather_than_zero() -> None:
    """A model with no rate must not come back as a priceable zero (#890)."""
    query = TimescaleSessionCostQuery(Mock())

    priced = query._calculate_cost(
        session_id="session-1",
        exec_result=None,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation=0,
        cache_read=0,
        agent_model="gpt-5.6-mini",
    )

    assert priced.cost is None
    assert not priced.is_priced
