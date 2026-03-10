"""Unit tests for aggregate phase intelligence (ISS-196).

Tests the Processor To-Do List pattern: aggregate decides "what's next"
after artifacts are collected for each phase.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
    ArtifactsCollectedCommand,
    CompletePhaseCommand,
    ProvisionWorkspaceCompletedCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
    AgentExecutionCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.ArtifactsCollectedForPhaseEvent import (
    ArtifactsCollectedForPhaseEvent,
)
from syn_domain.contexts.orchestration.domain.events.NextPhaseReadyEvent import (
    NextPhaseReadyEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
    WorkspaceProvisionedForPhaseEvent,
)

# =========================================================================
# Helpers
# =========================================================================

TWO_PHASE_DEFS = [
    PhaseDefinition(phase_id="p-1", name="Research", order=1),
    PhaseDefinition(phase_id="p-2", name="Implement", order=2),
]

THREE_PHASE_DEFS = [
    PhaseDefinition(phase_id="p-1", name="Research", order=1),
    PhaseDefinition(phase_id="p-2", name="Implement", order=2),
    PhaseDefinition(phase_id="p-3", name="Review", order=3, timeout_seconds=600),
]


def _make_started_aggregate(
    execution_id: str = "exec-1",
    phase_definitions: list[PhaseDefinition] | None = None,
) -> WorkflowExecutionAggregate:
    """Create an aggregate that has been started with phase definitions."""
    agg = WorkflowExecutionAggregate()
    cmd = StartExecutionCommand(
        execution_id=execution_id,
        workflow_id="wf-1",
        workflow_name="Test Workflow",
        total_phases=len(phase_definitions) if phase_definitions else 2,
        inputs={"topic": "test"},
        phase_definitions=phase_definitions,
    )
    agg._handle_command(cmd)
    return agg


def _get_new_events(agg: WorkflowExecutionAggregate, event_type: type) -> list:
    """Get uncommitted events of a specific type."""
    return [e.event for e in agg._uncommitted_events if isinstance(e.event, event_type)]


# =========================================================================
# StartExecution with phase_definitions
# =========================================================================


@pytest.mark.unit
class TestStartExecutionWithPhaseDefinitions:
    """Tests for StartExecutionCommand with phase_definitions."""

    def test_start_with_phase_definitions_stores_phases(self) -> None:
        """Phase definitions are stored in aggregate state."""
        agg = _make_started_aggregate(phase_definitions=TWO_PHASE_DEFS)
        assert len(agg._phase_definitions) == 2
        assert agg._phase_definitions[0].phase_id == "p-1"
        assert agg._phase_definitions[1].phase_id == "p-2"

    def test_start_with_phase_definitions_builds_order_map(self) -> None:
        """Phase order map is built from definitions."""
        agg = _make_started_aggregate(phase_definitions=TWO_PHASE_DEFS)
        assert agg._phase_order_map == {"p-1": 1, "p-2": 2}

    def test_start_without_phase_definitions_backward_compat(self) -> None:
        """StartExecution without phase_definitions still works (legacy mode)."""
        agg = _make_started_aggregate(phase_definitions=None)
        assert agg.status == ExecutionStatus.RUNNING
        assert agg._phase_definitions == []
        assert agg._phase_order_map == {}

    def test_phase_definitions_serialized_in_event(self) -> None:
        """Phase definitions are included in the WorkflowExecutionStartedEvent."""
        agg = _make_started_aggregate(phase_definitions=TWO_PHASE_DEFS)
        started_events = [e.event for e in agg._uncommitted_events]
        assert len(started_events) == 1
        evt = started_events[0]
        assert evt.phase_definitions is not None
        assert len(evt.phase_definitions) == 2
        assert evt.phase_definitions[0]["phase_id"] == "p-1"

    def test_phase_definitions_sorted_by_order(self) -> None:
        """Phases are sorted by order even if provided out-of-order."""
        reversed_defs = [
            PhaseDefinition(phase_id="p-2", name="Implement", order=2),
            PhaseDefinition(phase_id="p-1", name="Research", order=1),
        ]
        agg = _make_started_aggregate(phase_definitions=reversed_defs)
        assert agg._phase_definitions[0].phase_id == "p-1"
        assert agg._phase_definitions[1].phase_id == "p-2"


# =========================================================================
# ProvisionWorkspaceCompletedCommand
# =========================================================================


@pytest.mark.unit
class TestProvisionWorkspaceCompleted:
    """Tests for ProvisionWorkspaceCompletedCommand."""

    def test_emits_workspace_provisioned_event(self) -> None:
        """ProvisionWorkspaceCompleted emits WorkspaceProvisionedForPhaseEvent."""
        agg = _make_started_aggregate(phase_definitions=TWO_PHASE_DEFS)

        cmd = ProvisionWorkspaceCompletedCommand(
            execution_id="exec-1",
            phase_id="p-1",
            workspace_id="ws-123",
        )
        agg._handle_command(cmd)

        new_events = _get_new_events(agg, WorkspaceProvisionedForPhaseEvent)
        assert len(new_events) == 1
        assert new_events[0].phase_id == "p-1"
        assert new_events[0].workspace_id == "ws-123"

    def test_tracks_current_workspace_id(self) -> None:
        """Aggregate state tracks current workspace ID."""
        agg = _make_started_aggregate(phase_definitions=TWO_PHASE_DEFS)
        cmd = ProvisionWorkspaceCompletedCommand(
            execution_id="exec-1", phase_id="p-1", workspace_id="ws-123"
        )
        agg._handle_command(cmd)
        assert agg._current_phase_workspace_id == "ws-123"

    def test_rejected_when_not_running(self) -> None:
        """Provision rejected when execution is not RUNNING."""
        from decimal import Decimal

        from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            CompleteExecutionCommand,
        )

        agg = _make_started_aggregate(phase_definitions=TWO_PHASE_DEFS)
        agg._handle_command(
            CompleteExecutionCommand(
                execution_id="exec-1",
                completed_phases=2,
                total_phases=2,
                total_input_tokens=0,
                total_output_tokens=0,
                total_cost_usd=Decimal("0"),
                duration_seconds=0.0,
                artifact_ids=[],
            )
        )

        with pytest.raises(ValueError, match="Cannot provision workspace"):
            agg._handle_command(
                ProvisionWorkspaceCompletedCommand(
                    execution_id="exec-1", phase_id="p-1", workspace_id="ws-1"
                )
            )


# =========================================================================
# AgentExecutionCompletedCommand
# =========================================================================


@pytest.mark.unit
class TestAgentExecutionCompleted:
    """Tests for AgentExecutionCompletedCommand."""

    def test_emits_agent_execution_completed_event(self) -> None:
        """AgentExecutionCompleted emits AgentExecutionCompletedEvent."""
        agg = _make_started_aggregate(phase_definitions=TWO_PHASE_DEFS)

        cmd = AgentExecutionCompletedCommand(
            execution_id="exec-1",
            phase_id="p-1",
            session_id="sess-1",
            exit_code=0,
            input_tokens=100,
            output_tokens=50,
        )
        agg._handle_command(cmd)

        new_events = _get_new_events(agg, AgentExecutionCompletedEvent)
        assert len(new_events) == 1
        assert new_events[0].phase_id == "p-1"
        assert new_events[0].session_id == "sess-1"
        assert new_events[0].input_tokens == 100
        assert new_events[0].output_tokens == 50

    def test_rejected_when_not_running(self) -> None:
        """AgentExecutionCompleted rejected when not RUNNING."""
        from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            CancelExecutionCommand,
        )

        agg = _make_started_aggregate(phase_definitions=TWO_PHASE_DEFS)
        agg._handle_command(CancelExecutionCommand(execution_id="exec-1", phase_id="p-1"))

        with pytest.raises(ValueError, match="Cannot complete agent execution"):
            agg._handle_command(
                AgentExecutionCompletedCommand(
                    execution_id="exec-1", phase_id="p-1", session_id=None
                )
            )


# =========================================================================
# ArtifactsCollectedCommand — the key decision point
# =========================================================================


@pytest.mark.unit
class TestArtifactsCollected:
    """Tests for ArtifactsCollectedCommand — aggregate decides next phase."""

    def test_non_final_phase_emits_next_phase_ready(self) -> None:
        """ArtifactsCollected for non-final phase → emits NextPhaseReadyEvent."""
        agg = _make_started_aggregate(phase_definitions=TWO_PHASE_DEFS)

        cmd = ArtifactsCollectedCommand(
            execution_id="exec-1",
            phase_id="p-1",
            artifact_ids=["art-1"],
            first_content_preview="result content",
        )
        agg._handle_command(cmd)

        collected_events = _get_new_events(agg, ArtifactsCollectedForPhaseEvent)
        assert len(collected_events) == 1
        assert collected_events[0].artifact_ids == ["art-1"]

        next_events = _get_new_events(agg, NextPhaseReadyEvent)
        assert len(next_events) == 1
        assert next_events[0].completed_phase_id == "p-1"
        assert next_events[0].next_phase_id == "p-2"
        assert next_events[0].next_phase_order == 2

    def test_final_phase_does_not_emit_next_phase_ready(self) -> None:
        """ArtifactsCollected for final phase → does NOT emit NextPhaseReadyEvent."""
        agg = _make_started_aggregate(phase_definitions=TWO_PHASE_DEFS)

        cmd = ArtifactsCollectedCommand(
            execution_id="exec-1",
            phase_id="p-2",  # Final phase
            artifact_ids=["art-2"],
        )
        agg._handle_command(cmd)

        next_events = _get_new_events(agg, NextPhaseReadyEvent)
        assert len(next_events) == 0

        collected_events = _get_new_events(agg, ArtifactsCollectedForPhaseEvent)
        assert len(collected_events) == 1

    def test_three_phase_workflow_middle_phase(self) -> None:
        """Middle phase in 3-phase workflow emits NextPhaseReady for third phase."""
        agg = _make_started_aggregate(phase_definitions=THREE_PHASE_DEFS)

        cmd = ArtifactsCollectedCommand(
            execution_id="exec-1",
            phase_id="p-2",
            artifact_ids=["art-2"],
        )
        agg._handle_command(cmd)

        next_events = _get_new_events(agg, NextPhaseReadyEvent)
        assert len(next_events) == 1
        assert next_events[0].next_phase_id == "p-3"
        assert next_events[0].next_phase_order == 3

    def test_tracks_artifact_ids_in_state(self) -> None:
        """Artifact IDs accumulate in aggregate state."""
        agg = _make_started_aggregate(phase_definitions=TWO_PHASE_DEFS)

        agg._handle_command(
            ArtifactsCollectedCommand(
                execution_id="exec-1", phase_id="p-1", artifact_ids=["art-1", "art-2"]
            )
        )
        agg._handle_command(
            ArtifactsCollectedCommand(execution_id="exec-1", phase_id="p-2", artifact_ids=["art-3"])
        )

        assert agg._artifact_ids == ["art-1", "art-2", "art-3"]

    def test_no_phase_definitions_no_next_phase_event(self) -> None:
        """Without phase_definitions (legacy mode), no NextPhaseReady is emitted."""
        agg = _make_started_aggregate(phase_definitions=None)

        cmd = ArtifactsCollectedCommand(
            execution_id="exec-1",
            phase_id="p-1",
            artifact_ids=["art-1"],
        )
        agg._handle_command(cmd)

        # Should still emit ArtifactsCollectedForPhaseEvent
        collected_events = _get_new_events(agg, ArtifactsCollectedForPhaseEvent)
        assert len(collected_events) == 1

        # But no NextPhaseReady
        next_events = _get_new_events(agg, NextPhaseReadyEvent)
        assert len(next_events) == 0

    def test_rejected_when_not_running(self) -> None:
        """ArtifactsCollected rejected when not RUNNING."""
        from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            CancelExecutionCommand,
        )

        agg = _make_started_aggregate(phase_definitions=TWO_PHASE_DEFS)
        agg._handle_command(CancelExecutionCommand(execution_id="exec-1", phase_id="p-1"))

        with pytest.raises(ValueError, match="Cannot collect artifacts"):
            agg._handle_command(
                ArtifactsCollectedCommand(execution_id="exec-1", phase_id="p-1", artifact_ids=[])
            )


# =========================================================================
# Full lifecycle: existing commands still work with phase_definitions
# =========================================================================


@pytest.mark.unit
class TestBackwardCompatibility:
    """Existing aggregate behavior is unchanged."""

    def test_start_complete_phase_still_works(self) -> None:
        """StartPhase + CompletePhase still works alongside new events."""
        from decimal import Decimal

        agg = _make_started_aggregate(phase_definitions=TWO_PHASE_DEFS)

        # Start and complete phase using existing commands
        agg._handle_command(
            StartPhaseCommand(
                execution_id="exec-1",
                workflow_id="wf-1",
                phase_id="p-1",
                phase_name="Research",
                phase_order=1,
            )
        )

        agg._handle_command(
            CompletePhaseCommand(
                execution_id="exec-1",
                workflow_id="wf-1",
                phase_id="p-1",
                session_id="sess-1",
                artifact_id="art-1",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                cost_usd=Decimal("0.01"),
                duration_seconds=10.0,
            )
        )

        assert agg._completed_phases == 1
        assert agg.status == ExecutionStatus.RUNNING
