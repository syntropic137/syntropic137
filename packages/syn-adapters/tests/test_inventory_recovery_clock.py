"""Recovery ticks persist aggregate envelopes before reporting successful startup."""

from unittest.mock import AsyncMock

import pytest

from syn_adapters.session_inventory.clock import InventoryRecoveryClock
from syn_domain.contexts.agent_sessions import InventoryReconciliationSweepEvent

pytestmark = pytest.mark.unit


async def test_clock_persists_independent_aggregate_observations() -> None:
    store = AsyncMock()
    clock = InventoryRecoveryClock(store, interval_seconds=30)
    await clock.announce()
    await clock.announce()
    calls = store.append_events.await_args_list
    assert len(calls) == 2
    stream_ids: set[str] = set()
    for call in calls:
        assert call.kwargs["expected_version"] == 0
        (envelope,) = call.kwargs["events"]
        assert isinstance(envelope.event, InventoryReconciliationSweepEvent)
        assert envelope.metadata.aggregate_type == "SessionInventoryClock"
        assert envelope.metadata.aggregate_nonce == 1
        assert envelope.event.observed_at.tzinfo is not None
        stream = call.kwargs["stream_name"]
        assert stream == f"SessionInventoryClock-{envelope.metadata.aggregate_id}"
        stream_ids.add(stream)
    assert len(stream_ids) == 2


async def test_failed_initial_append_can_retry_start_without_orphan_task() -> None:
    store = AsyncMock()
    store.append_events.side_effect = ConnectionError("unavailable")
    clock = InventoryRecoveryClock(store, interval_seconds=3600)
    with pytest.raises(ConnectionError):
        await clock.start()
    store.append_events.side_effect = None
    await clock.start()
    await clock.start()
    assert store.append_events.await_count == 2
    await clock.stop()
    await clock.stop()
