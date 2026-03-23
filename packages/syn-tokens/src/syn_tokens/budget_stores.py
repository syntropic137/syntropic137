"""Budget storage backends for the spend tracker."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Protocol

from syn_tokens.models import SpendBudget

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Redis key prefixes
REDIS_BUDGET_PREFIX = "syn:budget:"


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
