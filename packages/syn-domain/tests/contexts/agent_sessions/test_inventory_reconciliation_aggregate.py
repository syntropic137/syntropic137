"""Management transitions survive replay and cannot skip publication."""

from __future__ import annotations

from uuid import uuid4

import pytest

from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
    ReconciliationStage,
)
from syn_domain.contexts.agent_sessions.domain.aggregate_inventory_reconciliation.InventoryReconciliationAggregate import (
    InventoryReconciliationAggregate,
)
from syn_domain.contexts.agent_sessions.domain.commands.AdvanceInventoryReconciliationCommand import (
    AdvanceInventoryReconciliationCommand,
)
from syn_domain.contexts.agent_sessions.domain.commands.RequestInventoryReconciliationCommand import (
    RequestInventoryReconciliationCommand,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import RunIdentity

pytestmark = pytest.mark.unit


def request() -> RequestInventoryReconciliationCommand:
    return RequestInventoryReconciliationCommand(
        aggregate_id="inventory-job-1",
        request=ReconciliationRequest(
            run=RunIdentity(source_instance_id="local", execution_id="run"),
            evidence_watermark=23,
            expected_head=None,
            snapshot_id=uuid4(),
            resolver_version="1",
        ),
    )


def test_replay_retains_next_work_without_replaying_infrastructure() -> None:
    command = request()
    aggregate = InventoryReconciliationAggregate()
    aggregate.request(command)
    aggregate.advance(
        AdvanceInventoryReconciliationCommand(
            aggregate_id=command.aggregate_id,
            stage=ReconciliationStage.PUBLISHING,
            revision="r1",
        )
    )
    restarted = InventoryReconciliationAggregate()
    restarted.rehydrate(aggregate.get_uncommitted_events())
    assert restarted.state == aggregate.state
    assert restarted.state is not None
    assert restarted.state.stage is ReconciliationStage.PUBLISHING
    assert not restarted.get_uncommitted_events()
    restarted.advance(
        AdvanceInventoryReconciliationCommand(
            aggregate_id=command.aggregate_id,
            stage=ReconciliationStage.COMPLETED,
            revision="r1",
        )
    )
    assert restarted.state.stage is ReconciliationStage.COMPLETED


def test_request_retry_cannot_rebind_an_existing_job() -> None:
    command = request()
    aggregate = InventoryReconciliationAggregate()
    aggregate.request(command)
    aggregate.request(command)
    assert len(aggregate.get_uncommitted_events()) == 1
    with pytest.raises(ValueError, match="idempotency"):
        aggregate.request(
            command.model_copy(
                update={
                    "request": command.request.model_copy(
                        update={"evidence_watermark": 24},
                    )
                }
            )
        )


def test_completion_requires_staging_and_exact_published_revision() -> None:
    command = request()
    aggregate = InventoryReconciliationAggregate()
    aggregate.request(command)
    completed = AdvanceInventoryReconciliationCommand(
        aggregate_id=command.aggregate_id,
        stage=ReconciliationStage.COMPLETED,
        revision="r1",
    )
    with pytest.raises(ValueError, match="publication"):
        aggregate.advance(completed)
    aggregate.advance(completed.model_copy(update={"stage": ReconciliationStage.PUBLISHING}))
    with pytest.raises(ValueError, match="publication"):
        aggregate.advance(completed.model_copy(update={"revision": "other"}))
    aggregate.advance(completed)
    aggregate.advance(completed)
    assert len(aggregate.get_uncommitted_events()) == 3
    with pytest.raises(ValueError, match="terminal"):
        aggregate.advance(completed.model_copy(update={"stage": ReconciliationStage.PUBLISHING}))


def test_failed_job_is_visible_and_cannot_silently_reset() -> None:
    command = request()
    aggregate = InventoryReconciliationAggregate()
    aggregate.request(command)
    failed = AdvanceInventoryReconciliationCommand(
        aggregate_id=command.aggregate_id,
        stage=ReconciliationStage.FAILED,
        failure_code="evidence_quota_exceeded",
    )
    aggregate.advance(failed)
    aggregate.advance(failed)
    assert aggregate.state is not None
    assert aggregate.state.failure_code == "evidence_quota_exceeded"
    with pytest.raises(ValueError, match="terminal"):
        aggregate.advance(
            AdvanceInventoryReconciliationCommand(
                aggregate_id=command.aggregate_id,
                stage=ReconciliationStage.PENDING,
            )
        )
