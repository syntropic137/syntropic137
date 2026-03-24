"""Singleton accessors for SpendTracker and TokenVendingService."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_tokens.budget_stores import InMemoryBudgetStore, RedisBudgetStore
from syn_tokens.token_stores import InMemoryTokenStore, RedisTokenStore

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from syn_tokens.budget_stores import BudgetStore
    from syn_tokens.spend import SpendTracker
    from syn_tokens.token_stores import TokenStore
    from syn_tokens.vending import TokenVendingService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Spend tracker singleton
# ---------------------------------------------------------------------------

_spend_tracker: SpendTracker | None = None
_budget_store: BudgetStore | None = None


def get_spend_tracker() -> SpendTracker:
    """Get the singleton spend tracker. Uses in-memory store by default."""
    global _spend_tracker, _budget_store

    if _spend_tracker is not None:
        return _spend_tracker

    from syn_tokens.spend import SpendTracker as _ST

    if _budget_store is None:
        _budget_store = InMemoryBudgetStore()

    _spend_tracker = _ST(_budget_store)
    logger.info("Spend tracker initialized (in-memory)")
    return _spend_tracker


async def configure_redis_spend_tracker(redis: Redis) -> SpendTracker:
    """Configure the spend tracker to use Redis."""
    global _spend_tracker, _budget_store

    from syn_tokens.spend import SpendTracker as _ST

    _budget_store = RedisBudgetStore(redis)
    _spend_tracker = _ST(_budget_store)
    logger.info("Spend tracker initialized (Redis)")
    return _spend_tracker


def reset_spend_tracker() -> None:
    """Reset the singleton (for testing)."""
    global _spend_tracker, _budget_store
    _spend_tracker = None
    if isinstance(_budget_store, InMemoryBudgetStore):
        _budget_store.clear()
    _budget_store = None


# ---------------------------------------------------------------------------
# Token vending service singleton
# ---------------------------------------------------------------------------

_token_vending_service: TokenVendingService | None = None
_token_store: TokenStore | None = None


def get_token_vending_service() -> TokenVendingService:
    """Get the singleton token vending service. Uses in-memory store by default."""
    global _token_vending_service, _token_store

    if _token_vending_service is not None:
        return _token_vending_service

    from syn_tokens.vending import TokenVendingService as _TVS

    if _token_store is None:
        _token_store = InMemoryTokenStore()

    _token_vending_service = _TVS(_token_store)
    logger.info("Token vending service initialized (in-memory)")
    return _token_vending_service


async def configure_redis_token_vending(redis: Redis) -> TokenVendingService:
    """Configure the token vending service to use Redis."""
    global _token_vending_service, _token_store

    from syn_tokens.vending import TokenVendingService as _TVS

    _token_store = RedisTokenStore(redis)
    _token_vending_service = _TVS(_token_store)
    logger.info("Token vending service initialized (Redis)")
    return _token_vending_service


def reset_token_vending_service() -> None:
    """Reset the singleton (for testing)."""
    global _token_vending_service, _token_store
    _token_vending_service = None
    if isinstance(_token_store, InMemoryTokenStore):
        _token_store.clear()
    _token_store = None
