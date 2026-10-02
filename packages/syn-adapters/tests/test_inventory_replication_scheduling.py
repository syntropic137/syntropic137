"""Real coordinator gating plus independent, supervised replication actions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from event_sourcing import EventEnvelope, EventMetadata, SubscriptionCoordinator
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.session_inventory.replication_supervisor import (
    InventoryReplicationWorkPort,
    ReplicationSupervisor,
)
from syn_domain.contexts.agent_sessions.domain.events.InventoryReconciliationSweepEvent import (
    InventoryReconciliationSweepEvent,
)
from syn_domain.contexts.agent_sessions.slices.replicate_session_inventory.projection import (
    InventoryReplicationProcessManager,
)

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


async def test_capture_and_inventory_are_independent_bounded_and_cancelled_on_stop() -> None:
    inventory = AsyncMock(spec=InventoryReplicationWorkPort)
    capture = AsyncMock(spec=InventoryReplicationWorkPort)
    release = asyncio.Event()
    started = [asyncio.Event() for _ in range(4)]
    stopped = [asyncio.Event() for _ in range(4)]

    def blocked(index: int) -> Callable[[], Awaitable[None]]:
        async def step() -> None:
            started[index].set()
            try:
                await release.wait()
            finally:
                stopped[index].set()

        return step

    operations = (
        inventory.enqueue_step,
        inventory.drain_step,
        capture.enqueue_step,
        capture.drain_step,
    )
    for index, operation in enumerate(operations):
        operation.side_effect = blocked(index)
    manager = InventoryReplicationProcessManager(
        ReplicationSupervisor(inventory, capture_work=capture)
    )
    coordinator = SubscriptionCoordinator(
        event_store=AsyncMock(), checkpoint_store=MemoryCheckpointStore(), projections=[manager]
    )
    coordinator.live_boundary_nonce = 100
    coordinator.is_catching_up = True
    try:
        await coordinator.dispatch_event(signal(50))
        for operation in operations:
            operation.assert_not_called()
        await asyncio.wait_for(coordinator.dispatch_event(signal(101)), timeout=1)
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started)), timeout=1)
        await asyncio.wait_for(coordinator.dispatch_event(signal(102)), timeout=1)
        for operation in operations:
            operation.assert_awaited_once()
    finally:
        await asyncio.wait_for(manager.stop(), timeout=1)
    assert all(event.is_set() for event in stopped)
    await manager.process_pending()
    for operation in operations:
        operation.assert_awaited_once()


def signal(position: int) -> EventEnvelope[InventoryReconciliationSweepEvent]:
    return EventEnvelope(
        event=InventoryReconciliationSweepEvent(observed_at=datetime.now(UTC)),
        metadata=EventMetadata(
            aggregate_nonce=1,
            aggregate_id=f"clock-{position}",
            aggregate_type="InventoryRecoveryClock",
            global_nonce=position,
            event_type=InventoryReconciliationSweepEvent.event_type,
        ),
    )


async def test_replay_never_starts_exporter_and_blocked_remote_drain_does_not_block_coordinator() -> (
    None
):
    work = AsyncMock(spec=InventoryReplicationWorkPort)
    drain_started, never_complete = asyncio.Event(), asyncio.Event()

    async def blocked_drain() -> None:
        drain_started.set()
        await never_complete.wait()

    work.drain_step.side_effect = blocked_drain
    manager = InventoryReplicationProcessManager(ReplicationSupervisor(work))
    coordinator = SubscriptionCoordinator(
        event_store=AsyncMock(), checkpoint_store=MemoryCheckpointStore(), projections=[manager]
    )
    coordinator.live_boundary_nonce = 100
    coordinator.is_catching_up = True
    await coordinator.dispatch_event(signal(50))
    work.enqueue_step.assert_not_called()
    work.drain_step.assert_not_called()
    await asyncio.wait_for(coordinator.dispatch_event(signal(101)), timeout=1)
    await asyncio.wait_for(drain_started.wait(), timeout=1)
    work.enqueue_step.assert_awaited_once()
    await asyncio.wait_for(coordinator.dispatch_event(signal(102)), timeout=1)
    assert work.drain_step.await_count == 1
    await manager.stop()
    count = work.enqueue_step.call_count
    await manager.process_pending()
    assert work.enqueue_step.call_count == count


async def test_background_failures_are_observed_without_logging_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    work = AsyncMock(spec=InventoryReplicationWorkPort)
    work.enqueue_step.side_effect = RuntimeError("private-token")
    work.drain_step.side_effect = RuntimeError("private-token")
    manager = InventoryReplicationProcessManager(ReplicationSupervisor(work))
    await manager.process_pending()
    await asyncio.sleep(0)
    await manager.stop()
    assert "private-token" not in caplog.text
    assert "durable work will retry" in caplog.text
    assert "exporter retains pending work" in caplog.text
