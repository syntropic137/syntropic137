"""Tests for the update-workflow-phase slice."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.domain.commands.UpdatePhasePromptCommand import (
    UpdatePhasePromptCommand,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowPhaseUpdatedEvent import (
    WorkflowPhaseUpdatedEvent,
)
from syn_domain.contexts.orchestration.slices.update_workflow_phase.UpdateWorkflowPhaseHandler import (
    UpdateWorkflowPhaseHandler,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope


# === Test Fixtures ===

_WORKFLOW_ID = "test-workflow-id"


def _create_aggregate_with_phases() -> WorkflowTemplateAggregate:
    """Create a workflow aggregate with two phases for testing updates."""
    aggregate = WorkflowTemplateAggregate()
    create_cmd = CreateWorkflowTemplateCommand(
        aggregate_id=_WORKFLOW_ID,
        name="Test Workflow",
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.SIMPLE,
        repository_url="https://github.com/test/repo",
        repository_ref="main",
        phases=[
            PhaseDefinition(
                phase_id="phase-1",
                name="Research Phase",
                order=1,
                description="Initial research",
                prompt_template="Original prompt for phase 1",
                model="sonnet",
                timeout_seconds=300,
                allowed_tools=["Bash", "Read"],
            ),
            PhaseDefinition(
                phase_id="phase-2",
                name="Analysis Phase",
                order=2,
                description="Deep analysis",
                prompt_template="Original prompt for phase 2",
            ),
        ],
    )
    aggregate._handle_command(create_cmd)
    aggregate.mark_events_as_committed()
    return aggregate


# === In-Memory Test Doubles ===


class InMemoryWorkflowRepository:
    """In-memory repository for testing updates."""

    def __init__(self) -> None:
        self.aggregates: dict[str, WorkflowTemplateAggregate] = {}
        self.saved_aggregates: list[WorkflowTemplateAggregate] = []

    def seed(self, aggregate: WorkflowTemplateAggregate) -> None:
        """Pre-load an aggregate for get_by_id."""
        if aggregate.id is not None:
            self.aggregates[aggregate.id] = aggregate

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        return self.aggregates.get(aggregate_id)

    async def save(self, aggregate: WorkflowTemplateAggregate) -> None:
        self.saved_aggregates.append(aggregate)


class InMemoryEventPublisher:
    """In-memory event publisher for testing."""

    def __init__(self) -> None:
        self.published_events: list[EventEnvelope[Any]] = []

    async def publish(self, events: list[EventEnvelope[DomainEvent]]) -> None:
        self.published_events.extend(events)


# === Aggregate Tests ===


@pytest.mark.unit
class TestUpdatePhasePrompt:
    """Tests for WorkflowTemplateAggregate.update_phase_prompt command handler."""

    def test_update_prompt_emits_event(self) -> None:
        """Updating a phase prompt should emit WorkflowPhaseUpdatedEvent."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt content",
        )

        aggregate._handle_command(command)

        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        assert events[0].event.event_type == "WorkflowPhaseUpdated"

    def test_update_prompt_updates_state(self) -> None:
        """Updated prompt should be reflected in aggregate state."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt content",
        )

        aggregate._handle_command(command)

        phase = next(p for p in aggregate.phases if p.phase_id == "phase-1")
        assert phase.prompt_template == "Updated prompt content"

    def test_update_preserves_other_phases(self) -> None:
        """Updating one phase should not affect other phases."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt content",
        )

        aggregate._handle_command(command)

        phase2 = next(p for p in aggregate.phases if p.phase_id == "phase-2")
        assert phase2.prompt_template == "Original prompt for phase 2"

    def test_reject_nonexistent_phase(self) -> None:
        """Should reject update for a phase_id that doesn't exist."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="nonexistent-phase",
            prompt_template="Some prompt",
        )

        with pytest.raises(ValueError, match="not found in workflow"):
            aggregate._handle_command(command)

    def test_reject_uncreated_aggregate(self) -> None:
        """Should reject update on an aggregate that hasn't been created."""
        aggregate = WorkflowTemplateAggregate()
        command = UpdatePhasePromptCommand(
            aggregate_id="some-id",
            phase_id="phase-1",
            prompt_template="Some prompt",
        )

        with pytest.raises(ValueError, match="does not exist"):
            aggregate._handle_command(command)

    def test_update_with_model_override(self) -> None:
        """Should update the model field when provided."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt",
            model="opus",
        )

        aggregate._handle_command(command)

        phase = next(p for p in aggregate.phases if p.phase_id == "phase-1")
        assert phase.model == "opus"

    def test_update_with_timeout_override(self) -> None:
        """Should update timeout_seconds when provided."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt",
            timeout_seconds=600,
        )

        aggregate._handle_command(command)

        phase = next(p for p in aggregate.phases if p.phase_id == "phase-1")
        assert phase.timeout_seconds == 600

    def test_update_with_allowed_tools_override(self) -> None:
        """Should update allowed_tools when provided."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt",
            allowed_tools=["Bash", "Read", "Write", "Grep"],
        )

        aggregate._handle_command(command)

        phase = next(p for p in aggregate.phases if p.phase_id == "phase-1")
        assert list(phase.allowed_tools) == ["Bash", "Read", "Write", "Grep"]

    def test_optional_fields_none_preserves_existing(self) -> None:
        """When optional fields are None, existing values should be preserved."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt",
            # model, timeout_seconds, allowed_tools all None
        )

        aggregate._handle_command(command)

        phase = next(p for p in aggregate.phases if p.phase_id == "phase-1")
        assert phase.model == "sonnet"  # preserved from creation
        assert phase.timeout_seconds == 300  # preserved from creation
        assert list(phase.allowed_tools) == ["Bash", "Read"]  # preserved


# === Handler Tests ===


class TestUpdateWorkflowPhaseHandler:
    """Tests for UpdateWorkflowPhaseHandler application service."""

    @pytest.mark.asyncio
    async def test_handler_loads_and_saves(self) -> None:
        """Handler should load the aggregate, dispatch, and save."""
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        aggregate = _create_aggregate_with_phases()
        repository.seed(aggregate)
        handler = UpdateWorkflowPhaseHandler(repository, publisher)

        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt",
        )

        result = await handler.handle(command)

        assert result == _WORKFLOW_ID
        assert len(repository.saved_aggregates) == 1

    @pytest.mark.asyncio
    async def test_handler_publishes_events(self) -> None:
        """Handler should publish the WorkflowPhaseUpdatedEvent."""
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        aggregate = _create_aggregate_with_phases()
        repository.seed(aggregate)
        handler = UpdateWorkflowPhaseHandler(repository, publisher)

        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt",
        )

        await handler.handle(command)

        assert len(publisher.published_events) == 1
        assert publisher.published_events[0].event.event_type == "WorkflowPhaseUpdated"

    @pytest.mark.asyncio
    async def test_handler_raises_on_missing_workflow(self) -> None:
        """Handler should raise ValueError when workflow not found."""
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = UpdateWorkflowPhaseHandler(repository, publisher)

        command = UpdatePhasePromptCommand(
            aggregate_id="nonexistent-id",
            phase_id="phase-1",
            prompt_template="Some prompt",
        )

        with pytest.raises(ValueError, match="not found"):
            await handler.handle(command)


# === Event Tests ===


class TestWorkflowPhaseUpdatedEvent:
    """Tests for WorkflowPhaseUpdatedEvent domain event."""

    def test_event_has_correct_type(self) -> None:
        """Event should have correct event_type from @event decorator."""
        event = WorkflowPhaseUpdatedEvent(
            workflow_id="test-id",
            phase_id="phase-1",
            prompt_template="Some prompt",
        )
        assert event.event_type == "WorkflowPhaseUpdated"

    def test_event_is_immutable(self) -> None:
        """Event should be immutable (frozen Pydantic model)."""
        from pydantic import ValidationError

        event = WorkflowPhaseUpdatedEvent(
            workflow_id="test-id",
            phase_id="phase-1",
            prompt_template="Some prompt",
        )

        with pytest.raises(ValidationError):
            event.prompt_template = "Changed"  # type: ignore[misc]
