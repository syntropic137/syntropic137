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

from syn_api.types import Ok
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

    async def list_costs_for_ids(self, execution_ids: list[str]) -> dict[str, ExecutionCost]:
        """Batched counterpart of get_execution_cost (issue #1077)."""
        if self.cost.execution_id in execution_ids:
            return {self.cost.execution_id: self.cost}
        return {}


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


CACHE_ONLY_COST_USD = Decimal("0.0171642")
"""A real dollar figure for a record whose only tokens are cache reads.

Cache reads are priced, so this is a legitimate nonzero cost sitting behind an
input + output total of zero. That combination is exactly what the 28-execution
sample used to verify #873 did not contain.
"""


def _cache_only_execution_cost() -> ExecutionCost:
    """An ExecutionCost whose tokens are all cache, with input == output == 0.

    Before #873 this record's ``total_tokens`` was 0, so both execution-detail
    paths rejected it and reported the caller's fallback dollar figure. After
    #873 ``total_tokens`` is nonzero. If dollar selection were gated on that
    number, this record would newly be accepted and the reported dollars would
    move - which #873 was explicitly not allowed to do.
    """
    return ExecutionCost(
        execution_id="exec-cache-only",
        workflow_id="wf-873",
        session_count=1,
        session_ids=["sess-cache-only"],
        total_cost_usd=CACHE_ONLY_COST_USD,
        token_cost_usd=CACHE_ONLY_COST_USD,
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=CACHE_READ_TOKENS,
        duration_ms=12_000.0,
        is_complete=True,
    )


@dataclass
class _StubWorkflowExecutionDetailProjection:
    detail: object

    async def get_by_id(self, execution_id: str) -> object | None:
        return self.detail


@dataclass
class _StubDetailProjectionManager:
    execution_cost: _StubExecutionCostProjection
    workflow_execution_detail: _StubWorkflowExecutionDetailProjection


@pytest.mark.unit
class TestCacheOnlyCostDollarInvariance:
    """A cache-only cost record must not change any dollar figure.

    ``ExecutionCost.total_tokens`` is a DISPLAY total and grew in #873. The
    availability gate on the two execution-detail paths must stay decoupled
    from it, or the display fix silently becomes a pricing change for records
    with input == output == 0.
    """

    def test_cache_only_record_is_not_treated_as_having_cost_data(self) -> None:
        cost = _cache_only_execution_cost()
        assert cost.total_tokens > 0, "display total must include cache (#873)"
        assert not cost.has_cost_data, (
            "availability must not follow the display total; a cache-only "
            "record was rejected before #873 and must stay rejected"
        )

    @pytest.mark.asyncio
    async def test_get_keeps_the_fallback_dollar_figure_for_cache_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``get()`` reported Decimal("0") here before #873; it still must."""
        from syn_api.routes.executions import queries
        from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
            WorkflowExecutionDetail,
        )

        cost = _cache_only_execution_cost()
        detail = WorkflowExecutionDetail(
            workflow_execution_id=cost.execution_id,
            workflow_id="wf-873",
            workflow_name="cache-only",
            status="completed",
        )
        manager = _StubDetailProjectionManager(
            execution_cost=_StubExecutionCostProjection(cost),
            workflow_execution_detail=_StubWorkflowExecutionDetailProjection(detail),
        )

        async def _noop_connect() -> None:
            return None

        monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
        monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)

        result = await queries.get(cost.execution_id)

        assert isinstance(result, Ok)
        assert result.value.total_cost_usd == Decimal("0"), (
            "cache-only record flipped the execution-detail dollar figure from "
            "the fallback to the cost read model - #873 moves no dollars"
        )

    @pytest.mark.asyncio
    async def test_enrich_costs_keeps_the_fallback_dollar_figure_for_cache_only(
        self,
    ) -> None:
        """``_enrich_costs()`` returned the caller's fallback here before #873."""
        from syn_api.routes.executions.queries import _enrich_costs

        cost = _cache_only_execution_cost()
        manager = _StubProjectionManager(_StubExecutionCostProjection(cost))
        fallback_cost = Decimal("0")
        fallback_tokens = 0

        enriched = await _enrich_costs(
            cost.execution_id,
            manager,
            phases=[],
            fallback_tokens=fallback_tokens,
            fallback_cost=fallback_cost,
        )
        tokens, dollars = enriched.total_tokens, enriched.total_cost_usd

        assert dollars == fallback_cost, (
            "cache-only record flipped _enrich_costs from the fallback dollar "
            "figure to exec_cost.total_cost_usd - #873 moves no dollars"
        )
        assert tokens == fallback_tokens

    @pytest.mark.asyncio
    async def test_a_priced_record_still_wins_over_the_fallback(self) -> None:
        """The guard must reject only cache-only records, not all enrichment."""
        from syn_api.routes.executions.queries import _enrich_costs

        cost = _execution_cost()
        manager = _StubProjectionManager(_StubExecutionCostProjection(cost))

        enriched = await _enrich_costs(
            cost.execution_id,
            manager,
            phases=[],
            fallback_tokens=0,
            fallback_cost=Decimal("0"),
        )
        tokens, dollars = enriched.total_tokens, enriched.total_cost_usd

        assert dollars == TOTAL_COST_USD
        assert tokens == EXPECTED_TOTAL
