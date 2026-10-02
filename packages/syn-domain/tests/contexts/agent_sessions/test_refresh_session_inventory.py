"""Explicit refresh retries retain original inputs, including a racing durable writer."""

from unittest.mock import AsyncMock

import pytest

from syn_domain.contexts.agent_sessions import (
    InventoryReconciliationAggregate,
    RefreshSessionInventoryHandler,
    RunIdentity,
)

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_retry_retains_original_watermark_and_new_key_refreshes() -> None:
    repository, evidence, inventory = AsyncMock(), AsyncMock(), AsyncMock()
    repository.get_by_id.return_value = None
    inventory.head.return_value = None
    evidence.watermark.return_value = 5
    handler = RefreshSessionInventoryHandler(repository, evidence, inventory)
    run = RunIdentity(source_instance_id="source", execution_id="run")
    first = await handler.handle(run, "request-one")
    aggregate = repository.save_new.call_args.args[0]
    assert aggregate.state.request.evidence_watermark == 5
    repository.get_by_id.return_value = aggregate
    evidence.watermark.return_value = 6
    assert await handler.handle(run, "request-one") == first
    evidence.watermark.assert_awaited_once()
    repository.save_new.assert_awaited_once()
    repository.get_by_id.return_value = None
    second = await handler.handle(run, "request-two")
    assert second != first
    assert repository.save_new.call_args.args[0].state.request.evidence_watermark == 6


@pytest.mark.asyncio
async def test_ambiguous_save_requires_durable_confirmation() -> None:
    repository, evidence, inventory = AsyncMock(), AsyncMock(), AsyncMock()
    repository.get_by_id.return_value = None

    async def saved_but_unacknowledged(aggregate: InventoryReconciliationAggregate) -> None:
        repository.get_by_id.return_value = aggregate
        raise RuntimeError("lost acknowledgment")

    repository.save_new.side_effect = saved_but_unacknowledged
    evidence.watermark.return_value = 0
    inventory.head.return_value = None
    handler = RefreshSessionInventoryHandler(repository, evidence, inventory)
    run = RunIdentity(source_instance_id="source", execution_id="run")
    assert await handler.handle(run, "key")
    repository.get_by_id.side_effect = [None, None]
    with pytest.raises(RuntimeError, match="lost acknowledgment"):
        await handler.handle(run, "key-two")


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["", " ", "a\x00b", "a" * 201])
async def test_invalid_key_does_not_touch_storage(key: str) -> None:
    repository, evidence, inventory = AsyncMock(), AsyncMock(), AsyncMock()
    handler = RefreshSessionInventoryHandler(repository, evidence, inventory)
    with pytest.raises(ValueError):
        await handler.handle(RunIdentity(source_instance_id="source", execution_id="run"), key)
    repository.get_by_id.assert_not_awaited()
