"""Reject an incomplete acquired input rather than publishing a partial graph."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import RunIdentity
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    RESOLVER_VERSION,
)
from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import EvidencePage

from .BuildInventorySnapshotHandler import BuildInventorySnapshotHandler

pytestmark = pytest.mark.unit


async def test_truncated_evidence_reader_cannot_stage_a_partial_inventory() -> None:
    evidence, inventory = AsyncMock(), AsyncMock()
    evidence.read.return_value = EvidencePage(watermark=5, items=())
    handler = BuildInventorySnapshotHandler(
        evidence, inventory, max_evidence_records=100, max_evidence_batches=100
    )
    request = ReconciliationRequest(
        run=RunIdentity(source_instance_id="test", execution_id="run"),
        evidence_watermark=5,
        expected_head=None,
        snapshot_id=uuid4(),
        resolver_version=RESOLVER_VERSION,
    )
    with pytest.raises(ValueError, match="truncated"):
        await handler.handle(request)
    inventory.stage.assert_not_awaited()
    inventory.publish.assert_not_awaited()


async def test_pending_job_cannot_silently_change_resolver_version() -> None:
    evidence, inventory = AsyncMock(), AsyncMock()
    handler = BuildInventorySnapshotHandler(
        evidence, inventory, max_evidence_records=100, max_evidence_batches=100
    )
    request = ReconciliationRequest(
        run=RunIdentity(source_instance_id="test", execution_id="run"),
        evidence_watermark=0,
        expected_head=None,
        snapshot_id=uuid4(),
        resolver_version="different/1",
    )
    with pytest.raises(ValueError, match="another resolver"):
        await handler.handle(request)
    evidence.read.assert_not_awaited()
    inventory.stage.assert_not_awaited()


async def test_projection_replay_writes_todo_without_executing_work() -> None:
    from syn_domain.contexts.agent_sessions.domain.aggregate_inventory_reconciliation.InventoryReconciliationAggregate import (
        InventoryReconciliationAggregate,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.RequestInventoryReconciliationCommand import (
        RequestInventoryReconciliationCommand,
    )

    from .projection import InventoryReconciliationProcessManager

    aggregate = InventoryReconciliationAggregate()
    aggregate.request(
        RequestInventoryReconciliationCommand(
            aggregate_id="management-job",
            request=ReconciliationRequest(
                run=RunIdentity(source_instance_id="test", execution_id="run"),
                evidence_watermark=0,
                expected_head=None,
                snapshot_id=uuid4(),
                resolver_version=RESOLVER_VERSION,
            ),
        )
    )
    jobs, work, checkpoints = AsyncMock(), AsyncMock(), AsyncMock()
    manager = InventoryReconciliationProcessManager(
        jobs,
        work,
        lease_seconds=60,
        retry_seconds=1,
        max_jobs_per_tick=1,
    )
    envelope = aggregate.get_uncommitted_events()[0]
    # The event store stamps these when the committed event is delivered.
    envelope = envelope.model_copy(
        update={
            "metadata": envelope.metadata.model_copy(
                update={
                    "event_type": envelope.event.event_type,
                    "global_nonce": 1,
                }
            )
        }
    )
    await manager.handle_event(envelope, checkpoints)
    jobs.project.assert_awaited_once()
    checkpoints.save_checkpoint.assert_awaited_once()
    work.schedule.assert_not_awaited()
    work.execute.assert_not_awaited()
    jobs.claim.assert_not_awaited()
