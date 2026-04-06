"""Spend Tracker for monitoring and limiting Claude API usage.

See Also:
    - docs/deployment/claude-api-security.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from syn_tokens.budget_stores import (
    InMemoryBudgetStore,
    RedisBudgetStore,
)
from syn_tokens.models import DEFAULT_BUDGETS, SpendBudget, WorkflowType
from syn_tokens.pricing import (
    CLAUDE_PRICING,
    DEFAULT_MODEL,
    calculate_cost,
)
from syn_tokens.singletons import (
    configure_redis_spend_tracker,
    get_spend_tracker,
    reset_spend_tracker,
)
from syn_tokens.threshold import ThresholdMonitor
from syn_tokens.usage_summary import build_usage_summary

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_tokens.budget_stores import (
        BudgetStore,
    )

logger = logging.getLogger(__name__)


@dataclass
class SpendCheckResult:
    """Result of a spend check."""

    allowed: bool
    reason: str | None = None
    budget: SpendBudget | None = None


class SpendTracker:
    """Tracks and limits Claude API spend per execution.

    Prevents runaway costs by:
    1. Pre-allocating budget before execution
    2. Tracking spend in real-time
    3. Rejecting requests that exceed budget
    4. Alerting on anomalous patterns

    Example:
        tracker = SpendTracker(store)

        # Allocate budget for execution
        budget = await tracker.allocate_budget("exec-123", WorkflowType.RESEARCH)

        # Check before making API call
        result = await tracker.check_budget("exec-123", input_tokens=1000, output_tokens=500)
        if not result.allowed:
            raise BudgetExceededError(result.reason)

        # Record actual usage after call
        await tracker.record_usage("exec-123", input_tokens=1000, output_tokens=487)
    """

    def __init__(
        self,
        store: BudgetStore,
        alert_callback: Callable[..., Awaitable[None]] | None = None,
        threshold_monitor: ThresholdMonitor | None = None,
    ) -> None:
        """Initialize the spend tracker.

        Args:
            store: Budget storage backend
            alert_callback: Optional async callback for alerts
            threshold_monitor: Optional threshold monitor (uses defaults if not provided)
        """
        self._store = store
        self._alert_callback = alert_callback
        self._threshold_monitor = threshold_monitor or ThresholdMonitor()

    async def allocate_budget(
        self,
        execution_id: str,
        workflow_type: WorkflowType | str,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        max_cost_usd: Decimal | None = None,
    ) -> SpendBudget:
        """Allocate spend budget for an execution.

        Budget defaults are based on workflow type but can be overridden.

        Args:
            execution_id: Unique execution identifier
            workflow_type: Type of workflow (affects defaults)
            max_input_tokens: Override max input tokens
            max_output_tokens: Override max output tokens
            max_cost_usd: Override max cost

        Returns:
            Allocated SpendBudget

        Raises:
            ValueError: If execution_id is empty
        """
        if not execution_id:
            msg = "execution_id is required"
            raise ValueError(msg)

        # Convert string to enum if needed
        if isinstance(workflow_type, str):
            workflow_type = WorkflowType(workflow_type)

        # Get defaults for workflow type
        defaults = DEFAULT_BUDGETS.get(workflow_type, DEFAULT_BUDGETS[WorkflowType.CUSTOM])

        budget = SpendBudget(
            execution_id=execution_id,
            workflow_type=workflow_type,
            max_input_tokens=max_input_tokens or int(defaults["max_input_tokens"]),
            max_output_tokens=max_output_tokens or int(defaults["max_output_tokens"]),
            max_cost_usd=max_cost_usd or Decimal(str(defaults["max_cost_usd"])),
        )

        await self._store.store(budget)

        logger.info(
            "Budget allocated (execution_id=%s, workflow=%s, max_in=%d, max_out=%d, max_cost=$%s)",
            execution_id,
            workflow_type.value,
            budget.max_input_tokens,
            budget.max_output_tokens,
            budget.max_cost_usd,
        )

        return budget

    async def get_budget(self, execution_id: str) -> SpendBudget | None:
        """Get budget for an execution."""
        return await self._store.get(execution_id)

    async def check_budget(
        self,
        execution_id: str,
        input_tokens: int,
        output_tokens: int,
        model: str = DEFAULT_MODEL,
    ) -> SpendCheckResult:
        """Check if budget allows a request.

        Should be called BEFORE making an API call to verify
        the execution has sufficient budget.

        Args:
            execution_id: Execution to check
            input_tokens: Estimated input tokens for request
            output_tokens: Estimated max output tokens
            model: Claude model for cost calculation

        Returns:
            SpendCheckResult with allowed flag and budget
        """
        budget = await self._store.get(execution_id)

        if budget is None:
            return SpendCheckResult(
                allowed=False,
                reason=f"No budget found for execution {execution_id}",
            )

        if budget.is_exhausted:
            return SpendCheckResult(
                allowed=False,
                reason="Budget exhausted",
                budget=budget,
            )

        estimated_cost = calculate_cost(input_tokens, output_tokens, model)

        if not budget.can_afford(input_tokens, output_tokens, estimated_cost):
            return SpendCheckResult(
                allowed=False,
                reason=f"Request would exceed budget (cost: ${estimated_cost:.4f})",
                budget=budget,
            )

        return SpendCheckResult(allowed=True, budget=budget)

    async def record_usage(
        self,
        execution_id: str,
        input_tokens: int,
        output_tokens: int,
        model: str = DEFAULT_MODEL,
    ) -> SpendBudget:
        """Record actual token usage after an API call.

        Should be called AFTER a successful API call with
        the actual token counts from the response.

        Args:
            execution_id: Execution to record usage for
            input_tokens: Actual input tokens used
            output_tokens: Actual output tokens used
            model: Claude model for cost calculation

        Returns:
            Updated SpendBudget

        Raises:
            ValueError: If no budget exists for execution
        """
        budget = await self._store.get(execution_id)

        if budget is None:
            msg = f"No budget found for execution {execution_id}"
            raise ValueError(msg)

        cost = calculate_cost(input_tokens, output_tokens, model)

        # Update usage
        budget.used_input_tokens += input_tokens
        budget.used_output_tokens += output_tokens
        budget.used_cost_usd += cost

        await self._store.update(budget)

        logger.debug(
            "Usage recorded (execution_id=%s, input=%d, output=%d, cost=$%s, total=$%s)",
            execution_id,
            input_tokens,
            output_tokens,
            cost,
            budget.used_cost_usd,
        )

        # Check for alert thresholds
        await self._check_thresholds(budget)

        return budget

    async def release_budget(self, execution_id: str) -> bool:
        """Release budget when execution completes.

        Args:
            execution_id: Execution to release budget for

        Returns:
            True if budget was released
        """
        deleted = await self._store.delete(execution_id)

        if deleted:
            logger.info("Budget released (execution_id=%s)", execution_id)

        return deleted

    async def get_usage_summary(self, execution_id: str) -> dict | None:
        """Get usage summary for an execution."""
        budget = await self._store.get(execution_id)
        if budget is None:
            return None
        return build_usage_summary(execution_id, budget)

    async def _check_thresholds(self, budget: SpendBudget) -> None:
        """Check if any thresholds are breached and send alerts."""
        alerts = self._threshold_monitor.check(budget)

        for alert in alerts:
            logger.warning(
                "Spend alert: %s (execution=%s, threshold=%s, metric=%s)",
                alert.message,
                alert.execution_id,
                alert.threshold,
                alert.metric,
            )

            if self._alert_callback:
                try:
                    await self._alert_callback(alert)
                except Exception as e:
                    logger.error("Alert callback failed: %s", e)
