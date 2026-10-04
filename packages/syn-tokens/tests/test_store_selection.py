"""ADR-060: the token and budget stores are durable outside test/offline."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_shared.in_memory import InMemoryAdapterError
from syn_shared.settings import reset_settings
from syn_tokens import singletons
from syn_tokens.budget_stores import InMemoryBudgetStore, RedisBudgetStore
from syn_tokens.redis_token_store import RedisTokenStore
from syn_tokens.token_stores import InMemoryTokenStore

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("REDIS_URL", "redis://redis.invalid:6379/0")
    reset_settings()
    singletons.reset_spend_tracker()
    singletons.reset_token_vending_service()
    yield
    singletons.reset_spend_tracker()
    singletons.reset_token_vending_service()
    monkeypatch.undo()
    reset_settings()


@pytest.mark.usefixtures("production")
class TestProduction:
    def test_in_memory_token_store_raises(self) -> None:
        with pytest.raises(InMemoryAdapterError):
            InMemoryTokenStore()

    def test_in_memory_budget_store_raises(self) -> None:
        with pytest.raises(InMemoryAdapterError):
            InMemoryBudgetStore()

    def test_token_vending_service_uses_redis(self) -> None:
        singletons.get_token_vending_service()
        assert isinstance(singletons._token_store, RedisTokenStore)

    def test_spend_tracker_uses_redis(self) -> None:
        singletons.get_spend_tracker()
        assert isinstance(singletons._budget_store, RedisBudgetStore)


def test_test_environment_keeps_in_memory_stores() -> None:
    singletons.reset_spend_tracker()
    singletons.reset_token_vending_service()
    singletons.get_spend_tracker()
    singletons.get_token_vending_service()
    assert isinstance(singletons._budget_store, InMemoryBudgetStore)
    assert isinstance(singletons._token_store, InMemoryTokenStore)
    singletons.reset_spend_tracker()
    singletons.reset_token_vending_service()
