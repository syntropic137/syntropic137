"""``total_tokens`` must mean the same thing in the cost and executions views.

Issue #873: ``/api/v1/costs/executions/{id}`` reported ``total_tokens`` as
input + output only, while ``/api/v1/executions/{id}`` reported all four
components. Live on dev, the same execution read 1,743 from one endpoint and
118,889 from the other - a 68x gap.

The gap hid because the DOLLAR figure was right. Pricing reads the four
component fields directly, so cost never went through the broken sum. It also
hid because the whole cost surface shared one mapping, so ``/costs/summary``
and ``/costs/executions`` agreed with each other perfectly. Two endpoints
agreeing is not evidence when they read the same code.

The only cheap check that catches this is a CROSS read model one: take a
single ExecutionCost, push it down the cost path and the executions path, and
assert the two answers are identical. Nothing in CI did that before this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost

# The live numbers from issue #873, so a regression reproduces the reported bug
# rather than an invented one.
INPUT_TOKENS = 35
OUTPUT_TOKENS = 1_708
CACHE_READ_TOKENS = 57_214
CACHE_CREATION_TOKENS = 59_932
EXPECTED_TOTAL = 118_889
BROKEN_TOTAL = 1_743  # what the costs endpoint used to report
TOTAL_COST_USD = Decimal("0.0932664")


def _execution_cost() -> ExecutionCost:
    return ExecutionCost(
        execution_id="exec-47b4fc8f0f8f",
        workflow_id="wf-873",
        session_count=1,
        session_ids=["sess-873"],
        total_cost_usd=TOTAL_COST_USD,
        token_cost_usd=TOTAL_COST_USD,
        input_tokens=INPUT_TOKENS,
        output_tokens=OUTPUT_TOKENS,
        cache_creation_tokens=CACHE_CREATION_TOKENS,
        cache_read_tokens=CACHE_READ_TOKENS,
        tool_calls=11,
        turns=4,
        duration_ms=36_000.0,
        is_complete=True,
    )


@dataclass
class _StubExecutionCostProjection:
    """Stands in for the execution_cost projection the executions route reads."""

    cost: ExecutionCost

    async def get_execution_cost(self, execution_id: str) -> ExecutionCost | None:
        return self.cost if execution_id == self.cost.execution_id else None


@dataclass
class _StubProjectionManager:
    execution_cost: _StubExecutionCostProjection


@pytest.mark.unit
class TestCrossReadModelTokenTotals:
    """The two read models must agree, or be named differently. No third option."""

    @pytest.mark.asyncio
    async def test_costs_and_executions_report_the_same_total_tokens(self) -> None:
        """The check that would have caught #873 the day it shipped."""
        from syn_api.routes.costs import execution_cost_to_data
        from syn_api.routes.executions.queries import _load_execution_enrichment

        cost = _execution_cost()

        # Cost read model path: /api/v1/costs/executions/{id}
        costs_total = execution_cost_to_data(cost).total_tokens

        # Executions read model path: /api/v1/executions/{id}
        manager = _StubProjectionManager(_StubExecutionCostProjection(cost))
        enrichment = await _load_execution_enrichment(
            manager,  # pyright: ignore[reportArgumentType] - structural stub
            [cost.execution_id],
        )
        executions_total = enrichment[cost.execution_id].total_tokens

        assert costs_total == executions_total, (
            f"total_tokens disagrees across read models: "
            f"costs={costs_total} executions={executions_total}. "
            "Either both sum all four components, or the cost figure needs a "
            "different field name (issue #873)."
        )
        assert costs_total == EXPECTED_TOTAL
        assert costs_total != BROKEN_TOTAL

    @pytest.mark.asyncio
    async def test_the_shared_total_is_not_silently_recomputed(self) -> None:
        """Cost must be untouched by the token fix - #873 changed no dollars."""
        from syn_api.routes.costs import execution_cost_to_data
        from syn_api.routes.executions.queries import _load_execution_enrichment

        cost = _execution_cost()
        manager = _StubProjectionManager(_StubExecutionCostProjection(cost))
        enrichment = await _load_execution_enrichment(
            manager,  # pyright: ignore[reportArgumentType] - structural stub
            [cost.execution_id],
        )

        assert execution_cost_to_data(cost).total_cost_usd == TOTAL_COST_USD
        assert enrichment[cost.execution_id].total_cost_usd == TOTAL_COST_USD


@pytest.mark.unit
class TestCostReadModelTotals:
    """``total_tokens`` reconciles with its own components on every cost model."""

    def test_execution_cost_total_equals_sum_of_its_four_components(self) -> None:
        cost = _execution_cost()
        assert cost.total_tokens == (
            cost.input_tokens
            + cost.output_tokens
            + cost.cache_creation_tokens
            + cost.cache_read_tokens
        )
        assert cost.total_tokens == EXPECTED_TOTAL

    def test_session_cost_total_equals_sum_of_its_four_components(self) -> None:
        cost = SessionCost(
            session_id="sess-873",
            input_tokens=INPUT_TOKENS,
            output_tokens=OUTPUT_TOKENS,
            cache_creation_tokens=CACHE_CREATION_TOKENS,
            cache_read_tokens=CACHE_READ_TOKENS,
        )
        assert cost.total_tokens == (
            cost.input_tokens
            + cost.output_tokens
            + cost.cache_creation_tokens
            + cost.cache_read_tokens
        )
        assert cost.total_tokens == EXPECTED_TOTAL

    def test_serialized_cost_dicts_carry_the_reconciling_total(self) -> None:
        """to_dict is what reaches the projection store; it must not drop cache."""
        exec_dict = _execution_cost().to_dict()
        assert exec_dict["total_tokens"] == EXPECTED_TOTAL

        session_dict = SessionCost(
            session_id="sess-873",
            input_tokens=INPUT_TOKENS,
            output_tokens=OUTPUT_TOKENS,
            cache_creation_tokens=CACHE_CREATION_TOKENS,
            cache_read_tokens=CACHE_READ_TOKENS,
        ).to_dict()
        assert session_dict["total_tokens"] == EXPECTED_TOTAL
