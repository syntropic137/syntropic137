"""Tests for Spend Tracker."""

from decimal import Decimal

import pytest

from aef_tokens.models import WorkflowType
from aef_tokens.spend import (
    InMemoryBudgetStore,
    SpendTracker,
    calculate_cost,
    reset_spend_tracker,
)


@pytest.fixture
def budget_store() -> InMemoryBudgetStore:
    """Create a fresh budget store."""
    return InMemoryBudgetStore()


@pytest.fixture
def spend_tracker(budget_store: InMemoryBudgetStore) -> SpendTracker:
    """Create a spend tracker with in-memory store."""
    return SpendTracker(budget_store)


@pytest.fixture(autouse=True)
def reset_singleton() -> None:
    """Reset singleton after each test."""
    yield
    reset_spend_tracker()


class TestCalculateCost:
    """Tests for cost calculation."""

    def test_sonnet_cost(self) -> None:
        """Should calculate Sonnet costs correctly."""
        # 1M input + 1M output at Sonnet prices
        cost = calculate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-3-5-sonnet-20241022",
        )

        # $3 input + $15 output = $18
        assert cost == Decimal("18.00")

    def test_opus_cost(self) -> None:
        """Should calculate Opus costs correctly."""
        # 1M input + 1M output at Opus prices
        cost = calculate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-3-opus-20240229",
        )

        # $15 input + $75 output = $90
        assert cost == Decimal("90.00")

    def test_small_request_cost(self) -> None:
        """Should calculate small request costs correctly."""
        # 1k input + 500 output at Sonnet
        cost = calculate_cost(
            input_tokens=1_000,
            output_tokens=500,
            model="claude-3-5-sonnet-20241022",
        )

        # $0.003 input + $0.0075 output = $0.0105
        expected = Decimal("1000") * Decimal("3.00") / Decimal("1000000")
        expected += Decimal("500") * Decimal("15.00") / Decimal("1000000")
        assert cost == expected

    def test_unknown_model_uses_default(self) -> None:
        """Should use Sonnet pricing for unknown models."""
        cost_unknown = calculate_cost(1000, 500, model="unknown-model")
        cost_sonnet = calculate_cost(1000, 500, model="claude-3-5-sonnet-20241022")
        assert cost_unknown == cost_sonnet


class TestSpendTracker:
    """Tests for SpendTracker."""

    @pytest.mark.asyncio
    async def test_allocate_budget_defaults(self, spend_tracker: SpendTracker) -> None:
        """Should allocate budget with workflow defaults."""
        budget = await spend_tracker.allocate_budget(
            execution_id="exec-123",
            workflow_type=WorkflowType.RESEARCH,
        )

        assert budget.execution_id == "exec-123"
        assert budget.workflow_type == WorkflowType.RESEARCH
        assert budget.max_input_tokens == 100_000
        assert budget.max_output_tokens == 50_000
        assert budget.max_cost_usd == Decimal("10.00")
        assert budget.used_input_tokens == 0
        assert budget.used_cost_usd == Decimal("0")

    @pytest.mark.asyncio
    async def test_allocate_budget_overrides(self, spend_tracker: SpendTracker) -> None:
        """Should allow overriding defaults."""
        budget = await spend_tracker.allocate_budget(
            execution_id="exec-123",
            workflow_type=WorkflowType.RESEARCH,
            max_input_tokens=200_000,
            max_cost_usd=Decimal("25.00"),
        )

        assert budget.max_input_tokens == 200_000
        assert budget.max_output_tokens == 50_000  # Default
        assert budget.max_cost_usd == Decimal("25.00")

    @pytest.mark.asyncio
    async def test_allocate_budget_string_workflow_type(self, spend_tracker: SpendTracker) -> None:
        """Should accept workflow type as string."""
        budget = await spend_tracker.allocate_budget(
            execution_id="exec-123",
            workflow_type="implementation",
        )

        assert budget.workflow_type == WorkflowType.IMPLEMENTATION

    @pytest.mark.asyncio
    async def test_allocate_budget_requires_execution_id(self, spend_tracker: SpendTracker) -> None:
        """Should require execution_id."""
        with pytest.raises(ValueError, match="execution_id is required"):
            await spend_tracker.allocate_budget(
                execution_id="",
                workflow_type=WorkflowType.RESEARCH,
            )

    @pytest.mark.asyncio
    async def test_check_budget_allowed(self, spend_tracker: SpendTracker) -> None:
        """Should allow request within budget."""
        await spend_tracker.allocate_budget(
            execution_id="exec-123",
            workflow_type=WorkflowType.RESEARCH,
        )

        result = await spend_tracker.check_budget(
            execution_id="exec-123",
            input_tokens=5_000,
            output_tokens=2_000,
        )

        assert result.allowed is True
        assert result.budget is not None

    @pytest.mark.asyncio
    async def test_check_budget_no_budget(self, spend_tracker: SpendTracker) -> None:
        """Should reject when no budget exists."""
        result = await spend_tracker.check_budget(
            execution_id="exec-123",
            input_tokens=5_000,
            output_tokens=2_000,
        )

        assert result.allowed is False
        assert "No budget found" in result.reason

    @pytest.mark.asyncio
    async def test_check_budget_exhausted(self, spend_tracker: SpendTracker) -> None:
        """Should reject when budget exhausted."""
        budget = await spend_tracker.allocate_budget(
            execution_id="exec-123",
            workflow_type=WorkflowType.QUICK_FIX,
            max_input_tokens=10_000,
        )

        # Use up the budget
        budget.used_input_tokens = 10_000
        await spend_tracker._store.update(budget)

        result = await spend_tracker.check_budget(
            execution_id="exec-123",
            input_tokens=1_000,
            output_tokens=500,
        )

        assert result.allowed is False
        assert "exhausted" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_record_usage(self, spend_tracker: SpendTracker) -> None:
        """Should record token usage."""
        await spend_tracker.allocate_budget(
            execution_id="exec-123",
            workflow_type=WorkflowType.RESEARCH,
        )

        budget = await spend_tracker.record_usage(
            execution_id="exec-123",
            input_tokens=5_000,
            output_tokens=2_000,
        )

        assert budget.used_input_tokens == 5_000
        assert budget.used_output_tokens == 2_000
        assert budget.used_cost_usd > Decimal("0")

    @pytest.mark.asyncio
    async def test_record_usage_accumulates(self, spend_tracker: SpendTracker) -> None:
        """Should accumulate usage across calls."""
        await spend_tracker.allocate_budget(
            execution_id="exec-123",
            workflow_type=WorkflowType.RESEARCH,
        )

        await spend_tracker.record_usage(
            execution_id="exec-123",
            input_tokens=5_000,
            output_tokens=2_000,
        )
        budget = await spend_tracker.record_usage(
            execution_id="exec-123",
            input_tokens=3_000,
            output_tokens=1_000,
        )

        assert budget.used_input_tokens == 8_000
        assert budget.used_output_tokens == 3_000

    @pytest.mark.asyncio
    async def test_record_usage_no_budget(self, spend_tracker: SpendTracker) -> None:
        """Should raise when no budget exists."""
        with pytest.raises(ValueError, match="No budget found"):
            await spend_tracker.record_usage(
                execution_id="exec-123",
                input_tokens=5_000,
                output_tokens=2_000,
            )

    @pytest.mark.asyncio
    async def test_release_budget(self, spend_tracker: SpendTracker) -> None:
        """Should release budget."""
        await spend_tracker.allocate_budget(
            execution_id="exec-123",
            workflow_type=WorkflowType.RESEARCH,
        )

        released = await spend_tracker.release_budget("exec-123")
        assert released is True

        budget = await spend_tracker.get_budget("exec-123")
        assert budget is None

    @pytest.mark.asyncio
    async def test_get_usage_summary(self, spend_tracker: SpendTracker) -> None:
        """Should return usage summary."""
        await spend_tracker.allocate_budget(
            execution_id="exec-123",
            workflow_type=WorkflowType.RESEARCH,
        )
        await spend_tracker.record_usage(
            execution_id="exec-123",
            input_tokens=80_000,
            output_tokens=40_000,
        )

        summary = await spend_tracker.get_usage_summary("exec-123")

        assert summary["execution_id"] == "exec-123"
        assert summary["input_tokens"]["used"] == 80_000
        assert summary["input_tokens"]["percent"] == 80.0
        assert summary["output_tokens"]["percent"] == 80.0

    @pytest.mark.asyncio
    async def test_alert_callback_on_threshold(self, budget_store: InMemoryBudgetStore) -> None:
        """Should call alert callback on threshold breach."""
        alerts_received = []

        async def alert_handler(alert):
            alerts_received.append(alert)

        tracker = SpendTracker(budget_store, alert_callback=alert_handler)

        await tracker.allocate_budget(
            execution_id="exec-123",
            workflow_type=WorkflowType.QUICK_FIX,
            max_input_tokens=10_000,
            max_cost_usd=Decimal("1.00"),
        )

        # Use 85% of budget
        await tracker.record_usage(
            execution_id="exec-123",
            input_tokens=8_500,
            output_tokens=0,
        )

        # Should have triggered warning alert
        assert len(alerts_received) > 0
        assert any(a.threshold == "warning" for a in alerts_received)
