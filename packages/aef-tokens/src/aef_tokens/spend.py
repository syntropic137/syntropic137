"""Spend Tracker for monitoring and limiting Claude API usage.

This service manages budget allocation and spend tracking:
- Allocate budgets per execution based on workflow type
- Track spend atomically (input tokens, output tokens, cost)
- Check budget before allowing requests
- Alert on threshold breaches

See Also:
    - docs/deployment/claude-api-security.md
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from aef_tokens.models import DEFAULT_BUDGETS, SpendBudget, WorkflowType

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Redis key prefixes
REDIS_BUDGET_PREFIX = "aef:budget:"

# Alert thresholds
ALERT_THRESHOLD_PERCENT = 80  # Alert at 80% budget usage
CRITICAL_THRESHOLD_PERCENT = 95  # Critical at 95%

# Claude pricing (per 1M tokens)
CLAUDE_PRICING = {
    "claude-3-5-sonnet-20241022": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
    "claude-3-opus-20240229": {
        "input": Decimal("15.00"),
        "output": Decimal("75.00"),
    },
    "claude-3-haiku-20240307": {
        "input": Decimal("0.25"),
        "output": Decimal("1.25"),
    },
}

DEFAULT_MODEL = "claude-3-5-sonnet-20241022"


@dataclass
class SpendCheckResult:
    """Result of a spend check."""

    allowed: bool
    reason: str | None = None
    budget: SpendBudget | None = None


@dataclass
class SpendAlert:
    """Alert for budget threshold breach."""

    execution_id: str
    workflow_type: str
    threshold: str  # "warning" or "critical"
    metric: str  # "input_tokens", "output_tokens", "cost"
    usage_percent: float
    message: str


class BudgetStore(Protocol):
    """Protocol for budget storage backends."""

    async def store(self, budget: SpendBudget) -> None:
        """Store a budget."""
        ...

    async def get(self, execution_id: str) -> SpendBudget | None:
        """Get a budget by execution ID."""
        ...

    async def update(self, budget: SpendBudget) -> None:
        """Update an existing budget."""
        ...

    async def delete(self, execution_id: str) -> bool:
        """Delete a budget. Returns True if deleted."""
        ...


class InMemoryBudgetStore:
    """In-memory budget store for testing."""

    def __init__(self) -> None:
        self._budgets: dict[str, SpendBudget] = {}

    async def store(self, budget: SpendBudget) -> None:
        """Store a budget."""
        self._budgets[budget.execution_id] = budget

    async def get(self, execution_id: str) -> SpendBudget | None:
        """Get a budget by execution ID."""
        return self._budgets.get(execution_id)

    async def update(self, budget: SpendBudget) -> None:
        """Update an existing budget."""
        self._budgets[budget.execution_id] = budget

    async def delete(self, execution_id: str) -> bool:
        """Delete a budget."""
        if execution_id in self._budgets:
            del self._budgets[execution_id]
            return True
        return False

    def clear(self) -> None:
        """Clear all budgets (for testing)."""
        self._budgets.clear()


class RedisBudgetStore:
    """Redis-backed budget store."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def store(self, budget: SpendBudget) -> None:
        """Store a budget."""
        key = f"{REDIS_BUDGET_PREFIX}{budget.execution_id}"
        await self._redis.set(key, json.dumps(budget.to_dict()))

    async def get(self, execution_id: str) -> SpendBudget | None:
        """Get a budget by execution ID."""
        key = f"{REDIS_BUDGET_PREFIX}{execution_id}"
        data = await self._redis.get(key)

        if data is None:
            return None

        return SpendBudget.from_dict(json.loads(data))

    async def update(self, budget: SpendBudget) -> None:
        """Update an existing budget (atomic via Redis)."""
        await self.store(budget)

    async def delete(self, execution_id: str) -> bool:
        """Delete a budget."""
        key = f"{REDIS_BUDGET_PREFIX}{execution_id}"
        deleted = await self._redis.delete(key)
        return deleted > 0


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = DEFAULT_MODEL,
) -> Decimal:
    """Calculate cost for token usage.

    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        model: Claude model name

    Returns:
        Cost in USD
    """
    pricing = CLAUDE_PRICING.get(model, CLAUDE_PRICING[DEFAULT_MODEL])

    input_cost = Decimal(input_tokens) * pricing["input"] / Decimal("1000000")
    output_cost = Decimal(output_tokens) * pricing["output"] / Decimal("1000000")

    return input_cost + output_cost


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
        alert_callback: Callable[[SpendAlert], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize the spend tracker.

        Args:
            store: Budget storage backend
            alert_callback: Optional async callback for alerts
        """
        self._store = store
        self._alert_callback = alert_callback

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
            "Budget allocated: execution=%s, type=%s, max_input=%d, max_output=%d, max_cost=$%s",
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
            "Usage recorded: execution=%s, input=%d, output=%d, cost=$%s, total=$%s",
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
            logger.info("Budget released: execution=%s", execution_id)

        return deleted

    async def get_usage_summary(self, execution_id: str) -> dict | None:
        """Get usage summary for an execution.

        Returns:
            Dictionary with usage stats or None if no budget
        """
        budget = await self._store.get(execution_id)

        if budget is None:
            return None

        return {
            "execution_id": execution_id,
            "workflow_type": budget.workflow_type.value,
            "input_tokens": {
                "used": budget.used_input_tokens,
                "max": budget.max_input_tokens,
                "remaining": budget.remaining_input_tokens,
                "percent": budget.input_usage_percent,
            },
            "output_tokens": {
                "used": budget.used_output_tokens,
                "max": budget.max_output_tokens,
                "remaining": budget.remaining_output_tokens,
                "percent": budget.output_usage_percent,
            },
            "cost_usd": {
                "used": str(budget.used_cost_usd),
                "max": str(budget.max_cost_usd),
                "remaining": str(budget.remaining_cost_usd),
                "percent": budget.cost_usage_percent,
            },
            "is_exhausted": budget.is_exhausted,
        }

    async def _check_thresholds(self, budget: SpendBudget) -> None:
        """Check if any thresholds are breached and send alerts."""
        alerts = []

        # Check input token threshold
        if budget.input_usage_percent >= CRITICAL_THRESHOLD_PERCENT:
            alerts.append(
                SpendAlert(
                    execution_id=budget.execution_id,
                    workflow_type=budget.workflow_type.value,
                    threshold="critical",
                    metric="input_tokens",
                    usage_percent=budget.input_usage_percent,
                    message=f"Input tokens at {budget.input_usage_percent:.1f}% of budget",
                )
            )
        elif budget.input_usage_percent >= ALERT_THRESHOLD_PERCENT:
            alerts.append(
                SpendAlert(
                    execution_id=budget.execution_id,
                    workflow_type=budget.workflow_type.value,
                    threshold="warning",
                    metric="input_tokens",
                    usage_percent=budget.input_usage_percent,
                    message=f"Input tokens at {budget.input_usage_percent:.1f}% of budget",
                )
            )

        # Check cost threshold
        if budget.cost_usage_percent >= CRITICAL_THRESHOLD_PERCENT:
            alerts.append(
                SpendAlert(
                    execution_id=budget.execution_id,
                    workflow_type=budget.workflow_type.value,
                    threshold="critical",
                    metric="cost",
                    usage_percent=budget.cost_usage_percent,
                    message=f"Cost at {budget.cost_usage_percent:.1f}% of budget (${budget.used_cost_usd:.2f})",
                )
            )
        elif budget.cost_usage_percent >= ALERT_THRESHOLD_PERCENT:
            alerts.append(
                SpendAlert(
                    execution_id=budget.execution_id,
                    workflow_type=budget.workflow_type.value,
                    threshold="warning",
                    metric="cost",
                    usage_percent=budget.cost_usage_percent,
                    message=f"Cost at {budget.cost_usage_percent:.1f}% of budget (${budget.used_cost_usd:.2f})",
                )
            )

        # Send alerts
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


# Singleton instance
_spend_tracker: SpendTracker | None = None
_budget_store: InMemoryBudgetStore | RedisBudgetStore | None = None


def get_spend_tracker() -> SpendTracker:
    """Get the singleton spend tracker.

    Uses in-memory store by default.
    """
    global _spend_tracker, _budget_store

    if _spend_tracker is not None:
        return _spend_tracker

    if _budget_store is None:
        _budget_store = InMemoryBudgetStore()

    _spend_tracker = SpendTracker(_budget_store)
    logger.info("Spend tracker initialized (in-memory)")

    return _spend_tracker


async def configure_redis_spend_tracker(redis: Redis) -> SpendTracker:
    """Configure the spend tracker to use Redis.

    Args:
        redis: Redis async client

    Returns:
        Configured SpendTracker
    """
    global _spend_tracker, _budget_store

    _budget_store = RedisBudgetStore(redis)
    _spend_tracker = SpendTracker(_budget_store)
    logger.info("Spend tracker initialized (Redis)")

    return _spend_tracker


def reset_spend_tracker() -> None:
    """Reset the singleton (for testing)."""
    global _spend_tracker, _budget_store
    _spend_tracker = None
    if isinstance(_budget_store, InMemoryBudgetStore):
        _budget_store.clear()
    _budget_store = None
