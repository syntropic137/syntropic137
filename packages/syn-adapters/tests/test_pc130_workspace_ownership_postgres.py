"""PC-130 ownership survives a projection reader restart on real Postgres.

Run locally with Docker/test-stack: this workspace cannot execute this file.
The matching producer/replay invariant is exercised without infrastructure in
test_containerless_workspace_uses_replayed_ownership.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from event_sourcing import EventEnvelope, MemoryCheckpointStore, ProjectionResult
from event_sourcing.core.envelope import decode_event, encode_payload, event_type_of

from syn_adapters.projection_stores.postgres_store import PostgresProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ProvisionWorkspaceCompletedCommand,
    StartExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.workspace_ownership.projection import (
    WorkspaceOwnershipProjection,
)

if TYPE_CHECKING:
    import asyncpg

pytestmark = pytest.mark.integration


async def test_provisioning_links_survive_a_new_postgres_reader(db_pool: asyncpg.Pool) -> None:
    store = PostgresProjectionStore(db_pool)
    projection = WorkspaceOwnershipProjection(store)
    checkpoints = MemoryCheckpointStore()
    suffix = uuid.uuid4().hex
    pairs = [
        (f"ws-first-{suffix}", f"exec-first-{suffix}"),
        (f"ws-second-{suffix}", f"exec-second-{suffix}"),
    ]
    try:
        for workspace_id, execution_id in pairs:
            aggregate = WorkflowExecutionAggregate()
            aggregate._handle_command(
                StartExecutionCommand(
                    execution_id=execution_id,
                    workflow_id="wf",
                    workflow_name="ownership",
                    total_phases=1,
                    inputs={},
                )
            )
            aggregate._handle_command(
                ProvisionWorkspaceCompletedCommand(
                    execution_id=execution_id,
                    phase_id="p",
                    workspace_id=workspace_id,
                )
            )
            written = aggregate._uncommitted_events[-1]
            decoded = decode_event(event_type_of(written.event), 1, encode_payload(written.event))
            envelope = EventEnvelope(
                event=decoded.event,
                metadata=written.metadata.model_copy(update={"event_type": decoded.event_type}),
            )
            for _ in range(2):
                assert (
                    await projection.handle_event(envelope, checkpoints) is ProjectionResult.SUCCESS
                )
        reader = WorkspaceOwnershipProjection(PostgresProjectionStore(db_pool))
        for workspace_id, execution_id in pairs:
            assert await reader.owners(workspace_id) == {execution_id}
    finally:
        for workspace_id, _ in pairs:
            await store.delete(projection.PROJECTION_NAME, workspace_id)
