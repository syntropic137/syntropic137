"""Level 4 Verification: Workflow Execution Roundtrip Tests.

These tests verify that workflow execution aggregates:
1. Persist correctly to the real event store
2. Can be reloaded with full state restored
3. Support concurrent modification detection

Level 4 = Outcome Verification: Real database, real persistence, real reads.

Run with:
    # Start infrastructure
    docker compose -f docker/docker-compose.dev.yaml up -d

    # Run integration tests
    uv run pytest -m integration packages/aef-domain/tests/integration/test_workflow_execution_roundtrip.py -v
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from event_sourcing import EventStoreRepository

    from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.integration
class TestWorkflowExecutionRoundtrip:
    """Level 4 tests: Verify workflow execution persists to real event store."""

    async def test_start_execution_persists_to_event_store(
        self,
        workflow_execution_repository: EventStoreRepository[WorkflowExecutionAggregate],
        unique_execution_id: str,
    ) -> None:
        """Level 4: Start command persists WorkflowExecutionStarted event."""
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )

        # Arrange: Create aggregate and execute command
        aggregate = WorkflowExecutionAggregate()
        command = StartExecutionCommand(
            execution_id=unique_execution_id,
            workflow_id="workflow-123",
            workflow_name="Test Workflow",
            total_phases=3,
            inputs={"topic": "testing"},
        )
        aggregate._handle_command(command)

        # Act: Save to REAL event store
        await workflow_execution_repository.save(aggregate)

        # Assert: Load back and verify state
        loaded = await workflow_execution_repository.load(unique_execution_id)

        assert loaded is not None, "Aggregate should be loadable from event store"
        assert loaded.id == unique_execution_id
        assert loaded.workflow_id == "workflow-123"
        assert loaded._workflow_name == "Test Workflow"
        assert loaded._total_phases == 3
        assert loaded.version == 1

    async def test_complete_phase_persists_to_event_store(
        self,
        workflow_execution_repository: EventStoreRepository[WorkflowExecutionAggregate],
        unique_execution_id: str,
    ) -> None:
        """Level 4: Phase completion persists PhaseCompleted event."""
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            CompletePhaseCommand,
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )

        # Arrange: Create and start execution
        aggregate = WorkflowExecutionAggregate()
        aggregate._handle_command(
            StartExecutionCommand(
                execution_id=unique_execution_id,
                workflow_id="workflow-456",
                workflow_name="Phase Test Workflow",
                total_phases=2,
                inputs={},
            )
        )
        await workflow_execution_repository.save(aggregate)

        # Act: Load, complete phase, save
        loaded = await workflow_execution_repository.load(unique_execution_id)
        assert loaded is not None

        loaded._handle_command(
            CompletePhaseCommand(
                execution_id=unique_execution_id,
                workflow_id="workflow-456",
                phase_id="phase-1",
                session_id="session-abc",
                artifact_id=None,
                input_tokens=1000,
                output_tokens=500,
                total_tokens=1500,
                cost_usd=Decimal("0.015"),
                duration_seconds=30.5,
            )
        )
        await workflow_execution_repository.save(loaded)

        # Assert: Reload and verify phase state
        reloaded = await workflow_execution_repository.load(unique_execution_id)
        assert reloaded is not None
        assert reloaded.version == 2
        assert reloaded._completed_phases == 1

    async def test_complete_execution_persists_to_event_store(
        self,
        workflow_execution_repository: EventStoreRepository[WorkflowExecutionAggregate],
        unique_execution_id: str,
    ) -> None:
        """Level 4: Execution completion persists WorkflowCompleted event."""
        from aef_domain.contexts.workflows._shared.ExecutionValueObjects import (
            ExecutionStatus,
        )
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            CompleteExecutionCommand,
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )

        # Arrange: Create and start execution
        aggregate = WorkflowExecutionAggregate()
        aggregate._handle_command(
            StartExecutionCommand(
                execution_id=unique_execution_id,
                workflow_id="workflow-789",
                workflow_name="Complete Test",
                total_phases=1,
                inputs={},
            )
        )
        await workflow_execution_repository.save(aggregate)

        # Act: Load, complete execution, save
        loaded = await workflow_execution_repository.load(unique_execution_id)
        assert loaded is not None

        loaded._handle_command(
            CompleteExecutionCommand(
                execution_id=unique_execution_id,
                completed_phases=1,
                total_phases=1,
                total_input_tokens=5000,
                total_output_tokens=2500,
                total_cost_usd=Decimal("0.075"),
                duration_seconds=120.0,
                artifact_ids=["artifact-1", "artifact-2"],
            )
        )
        await workflow_execution_repository.save(loaded)

        # Assert: Reload and verify completed state
        reloaded = await workflow_execution_repository.load(unique_execution_id)
        assert reloaded is not None
        assert reloaded.status == ExecutionStatus.COMPLETED
        assert reloaded._total_tokens == 7500
        assert reloaded._artifact_ids == ["artifact-1", "artifact-2"]

    async def test_fail_execution_persists_to_event_store(
        self,
        workflow_execution_repository: EventStoreRepository[WorkflowExecutionAggregate],
        unique_execution_id: str,
    ) -> None:
        """Level 4: Execution failure persists WorkflowFailed event."""
        from aef_domain.contexts.workflows._shared.ExecutionValueObjects import (
            ExecutionStatus,
        )
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            FailExecutionCommand,
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )

        # Arrange: Create and start execution
        aggregate = WorkflowExecutionAggregate()
        aggregate._handle_command(
            StartExecutionCommand(
                execution_id=unique_execution_id,
                workflow_id="workflow-fail",
                workflow_name="Fail Test",
                total_phases=3,
                inputs={},
            )
        )
        await workflow_execution_repository.save(aggregate)

        # Act: Load, fail execution, save
        loaded = await workflow_execution_repository.load(unique_execution_id)
        assert loaded is not None

        loaded._handle_command(
            FailExecutionCommand(
                execution_id=unique_execution_id,
                error="Something went wrong",
                error_type="RuntimeError",
                failed_phase_id="phase-2",
                completed_phases=1,
                total_phases=3,
            )
        )
        await workflow_execution_repository.save(loaded)

        # Assert: Reload and verify failed state
        reloaded = await workflow_execution_repository.load(unique_execution_id)
        assert reloaded is not None
        assert reloaded.status == ExecutionStatus.FAILED
        assert reloaded._error == "Something went wrong"

    async def test_optimistic_concurrency_on_real_store(
        self,
        workflow_execution_repository: EventStoreRepository[WorkflowExecutionAggregate],
        unique_execution_id: str,
    ) -> None:
        """Level 4: Verify optimistic concurrency works with real event store."""
        from event_sourcing.core.errors import ConcurrencyConflictError

        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            StartExecutionCommand,
            StartPhaseCommand,
            WorkflowExecutionAggregate,
        )

        # Arrange: Create and save execution
        aggregate = WorkflowExecutionAggregate()
        aggregate._handle_command(
            StartExecutionCommand(
                execution_id=unique_execution_id,
                workflow_id="workflow-concurrent",
                workflow_name="Concurrency Test",
                total_phases=5,
                inputs={},
            )
        )
        await workflow_execution_repository.save(aggregate)

        # Act: Load twice (simulating concurrent access)
        user1 = await workflow_execution_repository.load(unique_execution_id)
        user2 = await workflow_execution_repository.load(unique_execution_id)

        assert user1 is not None
        assert user2 is not None
        assert user1.version == user2.version == 1

        # User 1 makes change and saves
        user1._handle_command(
            StartPhaseCommand(
                execution_id=unique_execution_id,
                workflow_id="workflow-concurrent",
                phase_id="phase-1",
                phase_name="Phase 1",
                phase_order=1,
            )
        )
        await workflow_execution_repository.save(user1)

        # User 2 tries to save stale version
        user2._handle_command(
            StartPhaseCommand(
                execution_id=unique_execution_id,
                workflow_id="workflow-concurrent",
                phase_id="phase-2",
                phase_name="Phase 2",
                phase_order=2,
            )
        )

        # Assert: Should fail with concurrency conflict
        # Note: gRPC client may raise EventStoreError wrapping the conflict
        from event_sourcing.core.errors import EventStoreError

        with pytest.raises((ConcurrencyConflictError, EventStoreError)) as exc:
            await workflow_execution_repository.save(user2)

        # Verify it's a conflict error (either type)
        if isinstance(exc.value, ConcurrencyConflictError):
            assert exc.value.expected_version == 1
            assert exc.value.actual_version == 2
        else:
            # gRPC error message indicates conflict
            assert "precondition failed" in str(exc.value).lower()


class TestWorkflowExecutionMultipleEvents:
    """Level 4 tests: Verify multiple events replay correctly."""

    async def test_full_lifecycle_roundtrip(
        self,
        workflow_execution_repository: EventStoreRepository[WorkflowExecutionAggregate],
        unique_execution_id: str,
    ) -> None:
        """Level 4: Full execution lifecycle persists and replays correctly."""
        from aef_domain.contexts.workflows._shared.ExecutionValueObjects import (
            ExecutionStatus,
        )
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            CompleteExecutionCommand,
            CompletePhaseCommand,
            StartExecutionCommand,
            StartPhaseCommand,
            WorkflowExecutionAggregate,
        )

        # Step 1: Start execution
        aggregate = WorkflowExecutionAggregate()
        aggregate._handle_command(
            StartExecutionCommand(
                execution_id=unique_execution_id,
                workflow_id="workflow-full",
                workflow_name="Full Lifecycle",
                total_phases=2,
                inputs={"test": True},
            )
        )
        await workflow_execution_repository.save(aggregate)

        # Step 2: Start phase 1
        loaded = await workflow_execution_repository.load(unique_execution_id)
        assert loaded is not None
        loaded._handle_command(
            StartPhaseCommand(
                execution_id=unique_execution_id,
                workflow_id="workflow-full",
                phase_id="phase-1",
                phase_name="Research",
                phase_order=1,
                session_id="session-1",
            )
        )
        await workflow_execution_repository.save(loaded)

        # Step 3: Complete phase 1
        loaded = await workflow_execution_repository.load(unique_execution_id)
        assert loaded is not None
        loaded._handle_command(
            CompletePhaseCommand(
                execution_id=unique_execution_id,
                workflow_id="workflow-full",
                phase_id="phase-1",
                session_id="session-1",
                artifact_id="artifact-1",
                input_tokens=1000,
                output_tokens=500,
                total_tokens=1500,
                cost_usd=Decimal("0.01"),
                duration_seconds=60.0,
            )
        )
        await workflow_execution_repository.save(loaded)

        # Step 4: Start and complete phase 2
        loaded = await workflow_execution_repository.load(unique_execution_id)
        assert loaded is not None
        loaded._handle_command(
            StartPhaseCommand(
                execution_id=unique_execution_id,
                workflow_id="workflow-full",
                phase_id="phase-2",
                phase_name="Writing",
                phase_order=2,
                session_id="session-2",
            )
        )
        loaded._handle_command(
            CompletePhaseCommand(
                execution_id=unique_execution_id,
                workflow_id="workflow-full",
                phase_id="phase-2",
                session_id="session-2",
                artifact_id="artifact-2",
                input_tokens=2000,
                output_tokens=1000,
                total_tokens=3000,
                cost_usd=Decimal("0.02"),
                duration_seconds=90.0,
            )
        )
        await workflow_execution_repository.save(loaded)

        # Step 5: Complete execution
        loaded = await workflow_execution_repository.load(unique_execution_id)
        assert loaded is not None
        loaded._handle_command(
            CompleteExecutionCommand(
                execution_id=unique_execution_id,
                completed_phases=2,
                total_phases=2,
                total_input_tokens=3000,
                total_output_tokens=1500,
                total_cost_usd=Decimal("0.03"),
                duration_seconds=150.0,
                artifact_ids=["artifact-1", "artifact-2"],
            )
        )
        await workflow_execution_repository.save(loaded)

        # Final verification: Load and check all state
        final = await workflow_execution_repository.load(unique_execution_id)

        assert final is not None
        assert final.id == unique_execution_id
        assert final.workflow_id == "workflow-full"
        assert final.status == ExecutionStatus.COMPLETED
        assert final._completed_phases == 2
        assert final._total_tokens == 4500
        assert final._artifact_ids == ["artifact-1", "artifact-2"]
        assert final.version == 6  # 1 start + 2 phase starts + 2 phase completes + 1 complete
