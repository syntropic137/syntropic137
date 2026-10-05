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


def _redis_from_settings() -> Redis:
    """A Redis client for ``settings.redis_url``. Connects lazily, on first use."""
    from redis.asyncio import Redis as _Redis

    from syn_shared.settings import get_settings

    return _Redis.from_url(get_settings().redis_url)


def _uses_in_memory_stores() -> bool:
    from syn_shared.settings import get_settings

    return get_settings().uses_in_memory_stores


# ---------------------------------------------------------------------------
# Spend tracker singleton
# ---------------------------------------------------------------------------

_spend_tracker: SpendTracker | None = None
_budget_store: BudgetStore | None = None


def get_spend_tracker() -> SpendTracker:
    """Get the singleton spend tracker.

    Redis-backed unless ``settings.uses_in_memory_stores`` (ADR-060): the
    in-memory store loses every budget on restart, so it is test/offline only.
    """
    global _spend_tracker, _budget_store

    if _spend_tracker is not None:
        return _spend_tracker

    from syn_tokens.spend import SpendTracker as _ST

    if _budget_store is None:
        if _uses_in_memory_stores():
            _budget_store = InMemoryBudgetStore()
        else:
            _budget_store = RedisBudgetStore(_redis_from_settings())

    _spend_tracker = _ST(_budget_store)
    logger.info("Spend tracker initialized (%s)", type(_budget_store).__name__)
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
    """Get the singleton token vending service.

    Redis-backed unless ``settings.uses_in_memory_stores`` (ADR-060): the
    in-memory store loses every vended token on restart, so it is test/offline only.
    """
    global _token_vending_service, _token_store

    if _token_vending_service is not None:
        return _token_vending_service

    from syn_tokens.vending import TokenVendingService as _TVS

    if _token_store is None:
        if _uses_in_memory_stores():
            _token_store = InMemoryTokenStore()
        else:
            _token_store = RedisTokenStore(_redis_from_settings())

    _token_vending_service = _TVS(_token_store)
    logger.info("Token vending service initialized (%s)", type(_token_store).__name__)
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
