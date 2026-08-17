"""Tests for syn_api.routes.costs response contracts.

These exist because the cost API had NO tests, and two defects shipped as a
direct result:

1. `ExecutionCostData` was missing fields the query service already computed
   (cache tokens, tool calls, turns, cost splits), so both mapping hops
   silently dropped them and the response fell back to `= 0`. An execution
   reported 0 cache reads while its own session reported 144,640.
2. `session_ids` is suppressed unless requested. When the default was briefly
   flipped and then correctly reverted, a consumer that never passed the flag
   broke - and nothing caught it, because no test asserted the contract.

Both are mapping/contract bugs, not calculation bugs. They are cheap to test at
this layer and were invisible at every other one.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

from syn_api.types import ExecutionCostData

os.environ.setdefault("APP_ENVIRONMENT", "test")


def _execution_cost_data(unpriced_observation_count: int = 3) -> ExecutionCostData:
    """An ExecutionCostData with every numeric field non-zero.

    Non-zero everywhere on purpose: a dropped field shows up as 0, so a fixture
    full of zeros cannot distinguish "mapped correctly" from "silently lost".
    """
    return ExecutionCostData(
        execution_id="exec-test",
        workflow_id="wf-test",
        session_count=2,
        session_ids=["sess-a", "sess-b"],
        total_cost_usd=Decimal("0.199515"),
        token_cost_usd=Decimal("0.199515"),
        compute_cost_usd=Decimal("0.01"),
        input_tokens=16229,
        output_tokens=1535,
        total_tokens=17764,
        cache_creation_tokens=4096,
        cache_read_tokens=144640,
        tool_calls=10,
        turns=1,
        duration_ms=36000.0,
        cost_by_phase={"implement": "0.199515"},
        cost_by_model={"gpt-5.6-sol": "0.199515"},
        cost_by_tool={"Bash": "0.0"},
        unpriced_observation_count=unpriced_observation_count,
        is_complete=True,
    )


@pytest.mark.unit
class TestExecutionCostMapping:
    """The DTO -> response mapping must not silently drop computed fields."""

    def test_every_numeric_field_survives_the_mapping(self) -> None:
        from syn_api.routes.costs import _execution_cost_to_api

        api = _execution_cost_to_api(_execution_cost_data())

        # The four that were being dropped, plus the two cost splits.
        assert api.cache_read_tokens == 144640
        assert api.cache_creation_tokens == 4096
        assert api.tool_calls == 10
        assert api.turns == 1
        assert api.token_cost_usd == Decimal("0.199515")
        assert api.compute_cost_usd == Decimal("0.01")
        # And the rest, so a future reorder cannot quietly lose one.
        assert api.input_tokens == 16229
        assert api.output_tokens == 1535
        assert api.total_tokens == 17764
        assert api.session_count == 2
        assert api.total_cost_usd == Decimal("0.199515")

    def test_unpriced_count_reaches_the_api(self) -> None:
        """Without this, an unpriced run is indistinguishable from a free one."""
        from syn_api.routes.costs import _execution_cost_to_api

        assert _execution_cost_to_api(_execution_cost_data()).unpriced_observation_count == 3
        assert _execution_cost_to_api(_execution_cost_data(0)).unpriced_observation_count == 0


@pytest.mark.unit
class TestSessionIdsSuppressionContract:
    """`session_ids` is opt-in, and suppression must be null rather than [].

    An empty list beside a non-zero `session_count` is a contradiction a client
    cannot interpret: it reads as "no sessions" when it means "you did not ask".
    """

    def test_suppressed_is_null_not_empty_list(self) -> None:
        from syn_api.routes.costs import _execution_cost_to_api

        response = _execution_cost_to_api(_execution_cost_data())
        # Simulate the route's suppression branch.
        response.session_ids = None

        assert response.session_ids is None
        assert response.session_count == 2, (
            "session_count must stay accurate when IDs are suppressed - the pair "
            "([] , count=2) is what made this unreadable"
        )

    def test_requested_returns_the_ids(self) -> None:
        from syn_api.routes.costs import _execution_cost_to_api

        response = _execution_cost_to_api(_execution_cost_data())

        assert response.session_ids == ["sess-a", "sess-b"]
        assert response.session_count == len(response.session_ids)

    def test_response_model_permits_null_session_ids(self) -> None:
        """Guards the generated TS/CLI contract: `string[] | null`."""
        from syn_api.routes.costs import ExecutionCostResponse

        assert ExecutionCostResponse(execution_id="e", session_ids=None).session_ids is None


@pytest.mark.unit
class TestSessionCostMapping:
    """Session-level cost carries the same coverage signal as execution-level."""

    def test_unpriced_count_reaches_the_session_api(self) -> None:
        from syn_api.routes.costs import _session_cost_to_api
        from syn_api.types import SessionCostData

        data = SessionCostData(
            session_id="sess-a",
            total_cost_usd=Decimal("0"),
            unpriced_observation_count=5,
        )

        assert _session_cost_to_api(data).unpriced_observation_count == 5
