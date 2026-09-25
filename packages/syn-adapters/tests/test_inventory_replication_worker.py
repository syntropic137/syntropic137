"""A partial enqueue never advances the durable publication checkpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.exporter_transport import (
    ExporterInventoryTransport,
    ExporterTransportError,
)
from syn_adapters.session_inventory.publications import InventoryPublication
from syn_adapters.session_inventory.replication_jobs import (
    PostgresReplicationJobs,
    ReplicationLease,
)
from syn_adapters.session_inventory.replication_worker import InventoryReplicationWorker
from syn_domain.contexts.agent_sessions import (
    InventoryCounts,
    InventoryCoverage,
    InventorySnapshot,
    RunIdentity,
    SessionInventoryReadPort,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import CoverageState

pytestmark = pytest.mark.unit


def lease() -> ReplicationLease:
    return ReplicationLease(
        publication=InventoryPublication(
            snapshot=InventorySnapshot(
                snapshot_id=uuid4(),
                run=RunIdentity(source_instance_id="source", execution_id="run"),
                revision="r1",
                resolver_version="resolver/1",
                evidence_watermark=0,
                coverage=InventoryCoverage(state=CoverageState.UNKNOWN),
                counts=InventoryCounts(node=0, membership=0, edge=0, capture=0, gap=0),
            ),
            parent_snapshot_id=None,
            revision_sequence=1,
            first_record_sequence=1,
            record_high_watermark=0,
        ),
        offset=0,
        token=1,
        destination_id="destination",
    )


async def test_partial_enqueue_retries_same_checkpoint_and_never_calls_remote_drain() -> None:
    item = lease()
    jobs = AsyncMock(spec=PostgresReplicationJobs)
    jobs.claim.return_value = item
    transport = AsyncMock(spec=ExporterInventoryTransport)
    transport.enqueue.side_effect = [object(), ExporterTransportError("failed")]
    worker = InventoryReplicationWorker(
        jobs, AsyncMock(spec=SessionInventoryReadPort), transport, retry_seconds=7
    )
    assert await worker.enqueue_step()
    jobs.advance.assert_awaited_once_with(item, next_offset=0, retry_seconds=7)
    transport.drain.assert_not_called()
    jobs.advance.reset_mock()
    transport.enqueue.side_effect = None
    assert await worker.enqueue_step()
    jobs.advance.assert_awaited_once_with(item, next_offset=None)
    assert [call.args[0].operation for call in transport.enqueue.await_args_list] == [
        "stage",
        "publish",
        "stage",
        "publish",
    ]


async def test_no_pending_publication_does_not_spawn_exporter() -> None:
    jobs = AsyncMock(spec=PostgresReplicationJobs)
    jobs.claim.return_value = None
    transport = AsyncMock(spec=ExporterInventoryTransport)
    worker = InventoryReplicationWorker(jobs, AsyncMock(spec=SessionInventoryReadPort), transport)
    assert not await worker.enqueue_step()
    transport.enqueue.assert_not_called()
    await worker.drain_step()
    transport.drain.assert_awaited_once_with(limit=50)
