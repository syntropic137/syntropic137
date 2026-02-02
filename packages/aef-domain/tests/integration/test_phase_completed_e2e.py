"""E2E tests for PhaseCompleted event flow.

This test verifies the complete event sourcing flow:
1. Aggregate emits PhaseCompletedEvent via command handler
2. Repository saves event to event store
3. Subscription service picks up event
4. Projection handles event and updates read model

This is a critical regression test for the phase metrics feature.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest


@pytest.mark.e2e
class TestPhaseCompletedE2EFlow:
    """E2E tests for PhaseCompleted event flow through the system."""

    @pytest.fixture
    def mock_projection_store(self) -> AsyncMock:
        """Create mock projection store."""
        store = AsyncMock()
        store.get = AsyncMock(return_value=None)
        store.save = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_phase_completed_event_emitted_by_aggregate(self) -> None:
        """Test that PhaseCompletedEvent is properly emitted by aggregate."""
        from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            CompletePhaseCommand,
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )

        # Create and start execution
        aggregate = WorkflowExecutionAggregate()
        start_cmd = StartExecutionCommand(
            execution_id="exec-e2e-1",
            workflow_id="workflow-e2e-1",
            workflow_name="E2E Test Workflow",
            total_phases=3,
            inputs={"topic": "E2E test"},
        )
        aggregate._handle_command(start_cmd)
        aggregate.mark_events_as_committed()

        # Complete phase with metrics
        phase_cmd = CompletePhaseCommand(
            execution_id="exec-e2e-1",
            workflow_id="workflow-e2e-1",
            phase_id="research",
            session_id="session-e2e-1",
            artifact_id="artifact-e2e-1",
            input_tokens=500,
            output_tokens=1500,
            total_tokens=2000,
            cost_usd=Decimal("0.15"),
            duration_seconds=45.5,
        )
        aggregate._handle_command(phase_cmd)

        # Verify event was emitted with all metrics
        events = aggregate.get_uncommitted_events()
        assert len(events) == 1, "Expected exactly one PhaseCompleted event"

        event = events[0].event
        assert event.__class__.__name__ == "PhaseCompletedEvent"
        assert event.workflow_id == "workflow-e2e-1"
        assert event.execution_id == "exec-e2e-1"
        assert event.phase_id == "research"
        assert event.session_id == "session-e2e-1"
        assert event.artifact_id == "artifact-e2e-1"
        assert event.input_tokens == 500
        assert event.output_tokens == 1500
        assert event.total_tokens == 2000
        assert event.cost_usd == Decimal("0.15")
        assert event.duration_seconds == 45.5
        assert event.success is True

    @pytest.mark.asyncio
    async def test_phase_completed_projection_updates_phase_metrics(
        self, mock_projection_store: AsyncMock
    ) -> None:
        """Test that EXECUTION projection correctly updates phase metrics.

        Note: PhaseCompleted is handled by WorkflowExecutionDetailProjection,
        not WorkflowDetailProjection (which is for templates).
        """
        from aef_domain.contexts.orchestration.slices.get_execution_detail.projection import (
            WorkflowExecutionDetailProjection,
        )

        # Setup existing execution in projection
        existing_execution = {
            "execution_id": "exec-e2e-1",
            "workflow_id": "workflow-e2e-1",
            "workflow_name": "E2E Test Workflow",
            "status": "running",
            "started_at": "2024-12-04T00:01:00Z",
            "completed_at": None,
            "phases": [],
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": "0",
            "artifact_ids": [],
            "error_message": None,
        }

        mock_projection_store.get = AsyncMock(return_value=existing_execution)
        projection = WorkflowExecutionDetailProjection(mock_projection_store)

        # Simulate PhaseCompleted event data
        event_data = {
            "workflow_id": "workflow-e2e-1",
            "execution_id": "exec-e2e-1",
            "phase_id": "research",
            "phase_name": "Research",
            "completed_at": "2024-12-04T00:02:30Z",
            "success": True,
            "error_message": None,
            "artifact_id": "artifact-e2e-1",
            "session_id": "session-e2e-1",
            "input_tokens": 500,
            "output_tokens": 1500,
            "total_tokens": 2000,
            "cost_usd": Decimal("0.15"),
            "duration_seconds": 45.5,
        }

        # Handle the event
        await projection.on_phase_completed(event_data)

        # Verify projection store was called with updated data
        mock_projection_store.save.assert_called_once()
        call_args = mock_projection_store.save.call_args
        saved_data = call_args[0][2]

        # Verify phase was added with metrics
        assert len(saved_data["phases"]) == 1
        phase = saved_data["phases"][0]
        assert phase["phase_id"] == "research"
        assert phase["input_tokens"] == 500
        assert phase["output_tokens"] == 1500

        # Verify totals updated
        assert saved_data["total_input_tokens"] == 500
        assert saved_data["total_output_tokens"] == 1500

    @pytest.mark.asyncio
    async def test_projection_manager_routes_phase_completed(self) -> None:
        """Test that ProjectionManager correctly routes PhaseCompleted events.

        PhaseCompleted should route to EXECUTION projections, not template projections.
        """
        from aef_adapters.projections.manager import EVENT_HANDLERS

        # Verify PhaseCompleted is in the event handlers registry
        assert "PhaseCompleted" in EVENT_HANDLERS, "PhaseCompleted not registered in EVENT_HANDLERS"

        handlers = EVENT_HANDLERS["PhaseCompleted"]

        # Should route to workflow_execution_detail projection (not workflow_detail)
        projection_names = [h[0] for h in handlers]
        assert "workflow_execution_detail" in projection_names, (
            "PhaseCompleted not routed to workflow_execution_detail projection"
        )

        # Verify handler method name
        exec_detail_handler = next(h for h in handlers if h[0] == "workflow_execution_detail")
        assert exec_detail_handler[1] == "on_phase_completed", (
            "Wrong handler method for PhaseCompleted"
        )

    @pytest.mark.asyncio
    async def test_full_flow_aggregate_to_projection(
        self, mock_projection_store: AsyncMock
    ) -> None:
        """Test the complete flow from aggregate command to EXECUTION projection.

        This simulates what happens in production:
        1. ExecutionService calls aggregate command
        2. Aggregate emits event
        3. Event is "persisted" (mocked)
        4. Event is dispatched to EXECUTION projection
        5. Projection updates read model
        """
        from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            CompletePhaseCommand,
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )
        from aef_domain.contexts.orchestration.slices.get_execution_detail.projection import (
            WorkflowExecutionDetailProjection,
        )

        # Step 1: Create aggregate and execute commands
        aggregate = WorkflowExecutionAggregate()

        # Start execution
        start_cmd = StartExecutionCommand(
            execution_id="exec-full-e2e",
            workflow_id="workflow-full-e2e",
            workflow_name="Full E2E Workflow",
            total_phases=2,
            inputs={},
        )
        aggregate._handle_command(start_cmd)
        aggregate.mark_events_as_committed()

        # Complete phase
        phase_cmd = CompletePhaseCommand(
            execution_id="exec-full-e2e",
            workflow_id="workflow-full-e2e",
            phase_id="phase-1",
            session_id="session-full-1",
            artifact_id="artifact-full-1",
            input_tokens=1000,
            output_tokens=3000,
            total_tokens=4000,
            cost_usd=Decimal("0.25"),
            duration_seconds=60.0,
        )
        aggregate._handle_command(phase_cmd)

        # Step 2: Get emitted event
        events = aggregate.get_uncommitted_events()
        assert len(events) == 1

        emitted_event = events[0].event

        # Step 3: Convert event to dict (as subscription service does)
        if hasattr(emitted_event, "model_dump"):
            event_data = emitted_event.model_dump()
        elif hasattr(emitted_event, "to_dict"):
            event_data = emitted_event.to_dict()
        else:
            event_data = {
                "workflow_id": emitted_event.workflow_id,
                "execution_id": emitted_event.execution_id,
                "phase_id": emitted_event.phase_id,
                "phase_name": "Phase 1",
                "session_id": emitted_event.session_id,
                "artifact_id": emitted_event.artifact_id,
                "input_tokens": emitted_event.input_tokens,
                "output_tokens": emitted_event.output_tokens,
                "total_tokens": emitted_event.total_tokens,
                "cost_usd": emitted_event.cost_usd,
                "duration_seconds": emitted_event.duration_seconds,
            }

        # Add phase_name if not present (for test)
        if "phase_name" not in event_data:
            event_data["phase_name"] = "Phase 1"

        # Step 4: Setup EXECUTION projection with existing execution
        existing_execution = {
            "execution_id": "exec-full-e2e",
            "workflow_id": "workflow-full-e2e",
            "workflow_name": "Full E2E Workflow",
            "status": "running",
            "started_at": None,
            "completed_at": None,
            "phases": [],
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": "0",
            "artifact_ids": [],
            "error_message": None,
        }
        mock_projection_store.get = AsyncMock(return_value=existing_execution)

        # Step 5: Dispatch to EXECUTION projection
        projection = WorkflowExecutionDetailProjection(mock_projection_store)
        await projection.on_phase_completed(event_data)

        # Step 6: Verify projection was updated correctly
        mock_projection_store.save.assert_called_once()
        saved_data = mock_projection_store.save.call_args[0][2]

        # Phase should be added to phases list
        assert len(saved_data["phases"]) == 1
        phase_1 = saved_data["phases"][0]
        assert phase_1["phase_id"] == "phase-1"
        assert phase_1["input_tokens"] == 1000
        assert phase_1["output_tokens"] == 3000

        # Totals should be updated
        assert saved_data["total_input_tokens"] == 1000
        assert saved_data["total_output_tokens"] == 3000


class TestEventStoreIntegration:
    """Test event store integration for PhaseCompleted events.

    These tests use the memory event store to verify the complete flow
    without requiring external infrastructure.
    """

    @pytest.mark.asyncio
    async def test_events_persisted_to_event_store(self) -> None:
        """Test that aggregate events are actually persisted to event store."""
        from event_sourcing import EventStoreClientFactory, RepositoryFactory

        from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            CompletePhaseCommand,
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )

        # Create in-memory event store
        client = EventStoreClientFactory.create_memory_client()
        await client.connect()

        # Create repository
        factory = RepositoryFactory(client)
        repository = factory.create_repository(
            WorkflowExecutionAggregate,
            aggregate_type="WorkflowExecution",
        )

        # Create and save aggregate with events
        aggregate = WorkflowExecutionAggregate()

        # Start execution
        start_cmd = StartExecutionCommand(
            execution_id="exec-store-test",
            workflow_id="workflow-store-test",
            workflow_name="Store Test Workflow",
            total_phases=2,
            inputs={"test": "data"},
        )
        aggregate._handle_command(start_cmd)
        await repository.save(aggregate)

        # Complete phase
        phase_cmd = CompletePhaseCommand(
            execution_id="exec-store-test",
            workflow_id="workflow-store-test",
            phase_id="research",
            session_id="session-store-1",
            artifact_id="artifact-store-1",
            input_tokens=800,
            output_tokens=2400,
            total_tokens=3200,
            cost_usd=Decimal("0.20"),
            duration_seconds=55.0,
        )
        aggregate._handle_command(phase_cmd)
        await repository.save(aggregate)

        # Read events from event store
        stream_id = "WorkflowExecution-exec-store-test"
        events = await client.read_events(stream_id)

        assert len(events) == 2, f"Expected 2 events, got {len(events)}"

        # Verify event types
        event_types = [e.event.__class__.__name__ for e in events]
        assert "WorkflowExecutionStartedEvent" in event_types
        assert "PhaseCompletedEvent" in event_types

        # Verify PhaseCompleted event data
        phase_event = next(e for e in events if e.event.__class__.__name__ == "PhaseCompletedEvent")
        assert phase_event.event.input_tokens == 800
        assert phase_event.event.output_tokens == 2400
        assert phase_event.event.total_tokens == 3200

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_aggregate_can_be_reloaded_with_phase_events(self) -> None:
        """Test that aggregate state is correctly rebuilt from persisted events."""
        from event_sourcing import EventStoreClientFactory, RepositoryFactory

        from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            CompletePhaseCommand,
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )

        # Create in-memory event store
        client = EventStoreClientFactory.create_memory_client()
        await client.connect()

        # Create repository
        factory = RepositoryFactory(client)
        repository = factory.create_repository(
            WorkflowExecutionAggregate,
            aggregate_type="WorkflowExecution",
        )

        # Create aggregate and save events
        aggregate = WorkflowExecutionAggregate()

        start_cmd = StartExecutionCommand(
            execution_id="exec-reload-test",
            workflow_id="workflow-reload-test",
            workflow_name="Reload Test Workflow",
            total_phases=3,
            inputs={},
        )
        aggregate._handle_command(start_cmd)
        await repository.save(aggregate)

        # Complete two phases
        for i, phase_id in enumerate(["phase-1", "phase-2"], 1):
            phase_cmd = CompletePhaseCommand(
                execution_id="exec-reload-test",
                workflow_id="workflow-reload-test",
                phase_id=phase_id,
                session_id=f"session-{i}",
                artifact_id=f"artifact-{i}",
                input_tokens=100 * i,
                output_tokens=300 * i,
                total_tokens=400 * i,
                cost_usd=Decimal(f"0.0{i}"),
                duration_seconds=10.0 * i,
            )
            aggregate._handle_command(phase_cmd)
            await repository.save(aggregate)

        # Load aggregate fresh from event store
        reloaded = await repository.load("exec-reload-test")

        assert reloaded is not None
        assert reloaded.id == "exec-reload-test"
        assert reloaded._workflow_id == "workflow-reload-test"
        # The aggregate tracks completed phases via the event sourcing handler
        assert reloaded._completed_phases == 2

        await client.disconnect()
