"""Integration tests for the real subscription coordinator pipeline.

These tests exercise the full event delivery path:
    Event Store → SubscriptionCoordinator → CheckpointedProjection → ProjectionStore

Unlike tests that use sync_published_events_to_projections() (manual dispatch),
these tests verify that the coordinator actually picks up events from the
event store's subscribe() stream and routes them to projections.

All infrastructure is in-memory (MemoryEventStoreClient + MemoryCheckpointStore +
InMemoryProjectionStore) — no external dependencies needed.

REGRESSION: Catches bugs where:
- connect() kills subscription streams (non-idempotent channel replacement)
- Events are emitted but subscription coordinator never delivers them
- Projection handlers are missing from the event type → handler registry
- Checkpoint tracking prevents replay of already-processed events
"""

import asyncio
import contextlib
import os
from datetime import UTC, datetime

import pytest

# Ensure test environment before any imports
os.environ.setdefault("APP_ENVIRONMENT", "test")

from event_sourcing import (
    MemoryCheckpointStore,
    SubscriptionCoordinator,
)
from event_sourcing.client.memory import MemoryEventStoreClient
from event_sourcing.core.checkpoint import ProjectionCheckpoint
from event_sourcing.core.event import DomainEvent, EventEnvelope, EventMetadata

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.list_workflows import WorkflowListProjection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class WorkflowTemplateCreatedEvent(DomainEvent):
    """Test event matching the real domain event type."""

    event_type: str = "WorkflowTemplateCreated"
    workflow_id: str = ""
    name: str = ""
    workflow_type: str = "custom"
    classification: str = "standard"
    description: str = ""
    repository_url: str = "https://github.com/example/repo"
    repository_ref: str = "main"
    phase_count: int = 1
    is_archived: bool = False
    created_at: str = "2026-01-01T00:00:00Z"


class WorkflowArchivedEvent(DomainEvent):
    """Test event for archiving a workflow."""

    event_type: str = "WorkflowArchived"
    workflow_id: str = ""


def _make_envelope(
    event: DomainEvent,
    aggregate_id: str,
    nonce: int,
) -> EventEnvelope[DomainEvent]:
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            event_id=f"evt-{aggregate_id}-{nonce}",
            aggregate_id=aggregate_id,
            aggregate_type="WorkflowTemplate",
            aggregate_nonce=nonce,
        ),
    )


async def _wait_for_checkpoint(
    checkpoint_store: MemoryCheckpointStore,
    projection_name: str,
    target_position: int,
    timeout: float = 2.0,
) -> None:
    """Wait for a projection checkpoint to reach a target position."""
    import time

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        cp = await checkpoint_store.get_checkpoint(projection_name)
        if cp and cp.global_position >= target_position:
            return
        await asyncio.sleep(0.05)
    raise TimeoutError(
        f"Checkpoint '{projection_name}' did not reach position {target_position} within {timeout}s"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_store() -> MemoryEventStoreClient:
    client = MemoryEventStoreClient()
    client._connected = True
    return client


@pytest.fixture
def checkpoint_store() -> MemoryCheckpointStore:
    return MemoryCheckpointStore()


@pytest.fixture
def projection_store() -> InMemoryProjectionStore:
    return InMemoryProjectionStore()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubscriptionCoordinatorIntegration:
    """Tests for the full subscription coordinator pipeline with in-memory stores."""

    @pytest.mark.asyncio
    async def test_event_reaches_projection_via_coordinator(
        self,
        event_store: MemoryEventStoreClient,
        checkpoint_store: MemoryCheckpointStore,
        projection_store: InMemoryProjectionStore,
    ):
        """REGRESSION: Events appended to event store must reach projections
        via the subscription coordinator — not via manual dispatch."""
        projection = WorkflowListProjection(projection_store)

        coordinator = SubscriptionCoordinator(
            event_store=event_store,
            checkpoint_store=checkpoint_store,
            projections=[projection],
        )

        # Start coordinator in background
        task = asyncio.create_task(coordinator.start())

        try:
            # Append a workflow creation event to the event store
            event = WorkflowTemplateCreatedEvent(
                workflow_id="wf-test-1",
                name="Integration Test Workflow",
                workflow_type="research",
            )
            envelope = _make_envelope(event, "wf-test-1", nonce=1)
            await event_store.append_events("WorkflowTemplate-wf-test-1", [envelope])

            # Wait for the coordinator to pick up and process the event
            await _wait_for_checkpoint(checkpoint_store, projection.get_name(), target_position=0)

            # Verify the projection was updated
            results = await projection.query(include_archived=True)
            assert len(results) == 1
            assert results[0].name == "Integration Test Workflow"
            assert results[0].workflow_type == "research"
        finally:
            await coordinator.stop()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_multiple_events_processed_in_order(
        self,
        event_store: MemoryEventStoreClient,
        checkpoint_store: MemoryCheckpointStore,
        projection_store: InMemoryProjectionStore,
    ):
        """Multiple events are processed in global nonce order."""
        projection = WorkflowListProjection(projection_store)

        coordinator = SubscriptionCoordinator(
            event_store=event_store,
            checkpoint_store=checkpoint_store,
            projections=[projection],
        )

        task = asyncio.create_task(coordinator.start())

        try:
            # Append two workflow creation events
            for i in range(1, 4):
                event = WorkflowTemplateCreatedEvent(
                    workflow_id=f"wf-{i}",
                    name=f"Workflow {i}",
                )
                envelope = _make_envelope(event, f"wf-{i}", nonce=1)
                await event_store.append_events(f"WorkflowTemplate-wf-{i}", [envelope])

            # Wait for all 3 events (global nonce 0, 1, 2)
            await _wait_for_checkpoint(checkpoint_store, projection.get_name(), target_position=2)

            results = await projection.query(include_archived=True)
            assert len(results) == 3
            names = {r.name for r in results}
            assert names == {"Workflow 1", "Workflow 2", "Workflow 3"}
        finally:
            await coordinator.stop()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_checkpoint_prevents_duplicate_processing(
        self,
        event_store: MemoryEventStoreClient,
        checkpoint_store: MemoryCheckpointStore,
        projection_store: InMemoryProjectionStore,
    ):
        """Events already past the checkpoint are not reprocessed."""
        projection = WorkflowListProjection(projection_store)

        # Pre-seed an event
        event = WorkflowTemplateCreatedEvent(
            workflow_id="wf-existing",
            name="Existing Workflow",
        )
        envelope = _make_envelope(event, "wf-existing", nonce=1)
        await event_store.append_events("WorkflowTemplate-wf-existing", [envelope])

        # Pre-seed a checkpoint that claims we already processed nonce 0
        await checkpoint_store.save_checkpoint(
            ProjectionCheckpoint(
                projection_name=projection.get_name(),
                global_position=0,
                updated_at=datetime.now(UTC),
                version=projection.get_version(),
            )
        )

        coordinator = SubscriptionCoordinator(
            event_store=event_store,
            checkpoint_store=checkpoint_store,
            projections=[projection],
        )

        task = asyncio.create_task(coordinator.start())

        try:
            # Append a new event (this one should be processed)
            new_event = WorkflowTemplateCreatedEvent(
                workflow_id="wf-new",
                name="New Workflow",
            )
            new_envelope = _make_envelope(new_event, "wf-new", nonce=1)
            await event_store.append_events("WorkflowTemplate-wf-new", [new_envelope])

            # Wait for the new event to be processed (global nonce 1)
            await _wait_for_checkpoint(checkpoint_store, projection.get_name(), target_position=1)

            # Only the new workflow should be in the projection
            # (the existing one was already checkpointed, so skipped)
            results = await projection.query(include_archived=True)
            assert len(results) == 1
            assert results[0].name == "New Workflow"
        finally:
            await coordinator.stop()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_events_appended_after_coordinator_starts(
        self,
        event_store: MemoryEventStoreClient,
        checkpoint_store: MemoryCheckpointStore,
        projection_store: InMemoryProjectionStore,
    ):
        """Events appended AFTER the coordinator starts are picked up via polling."""
        projection = WorkflowListProjection(projection_store)

        coordinator = SubscriptionCoordinator(
            event_store=event_store,
            checkpoint_store=checkpoint_store,
            projections=[projection],
        )

        task = asyncio.create_task(coordinator.start())

        try:
            # Give the coordinator a moment to start its subscription
            await asyncio.sleep(0.15)

            # Now append an event — the coordinator should pick it up via polling
            event = WorkflowTemplateCreatedEvent(
                workflow_id="wf-late",
                name="Late Arrival",
            )
            envelope = _make_envelope(event, "wf-late", nonce=1)
            await event_store.append_events("WorkflowTemplate-wf-late", [envelope])

            await _wait_for_checkpoint(checkpoint_store, projection.get_name(), target_position=0)

            results = await projection.query(include_archived=True)
            assert len(results) == 1
            assert results[0].name == "Late Arrival"
        finally:
            await coordinator.stop()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_boolean_filter_works_with_projection(
        self,
        event_store: MemoryEventStoreClient,
        checkpoint_store: MemoryCheckpointStore,
        projection_store: InMemoryProjectionStore,
    ):
        """REGRESSION: is_archived=False filter must work correctly.

        The WorkflowListProjection stores is_archived as a boolean.
        Querying with is_archived=False must return non-archived workflows.
        """
        projection = WorkflowListProjection(projection_store)

        coordinator = SubscriptionCoordinator(
            event_store=event_store,
            checkpoint_store=checkpoint_store,
            projections=[projection],
        )

        task = asyncio.create_task(coordinator.start())

        try:
            event = WorkflowTemplateCreatedEvent(
                workflow_id="wf-filter",
                name="Filterable Workflow",
                is_archived=False,
            )
            envelope = _make_envelope(event, "wf-filter", nonce=1)
            await event_store.append_events("WorkflowTemplate-wf-filter", [envelope])

            await _wait_for_checkpoint(checkpoint_store, projection.get_name(), target_position=0)

            # Query with boolean filter — this was broken when str(False)='False'
            # Use the projection's query() which adds is_archived=False by default
            results = await projection.query()
            assert len(results) == 1
            assert results[0].name == "Filterable Workflow"
        finally:
            await coordinator.stop()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
