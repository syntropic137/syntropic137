"""Tests for model-aware session cost calculation."""

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


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5.6", Decimal("75.0")),
        ("claude-sonnet-4-20250514", Decimal("18.00")),
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


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5.6", Decimal("75.0")),
        ("claude-sonnet-4-20250514", Decimal("18.00")),
    ],
)
def test_timescale_cost_calculation_uses_resolved_model(model: str, expected: Decimal) -> None:
    query = TimescaleSessionCostQuery(Mock())

    total_cost = query._calculate_cost(
        exec_result=None,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation=0,
        cache_read=0,
        agent_model=model,
    )

    assert total_cost == expected
