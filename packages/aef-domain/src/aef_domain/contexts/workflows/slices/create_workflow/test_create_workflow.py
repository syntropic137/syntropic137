"""Tests for the create-workflow slice."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aef_domain.contexts.workflows.domain.WorkflowAggregate import (
    WorkflowAggregate,
    WorkflowStatus,
)
from aef_domain.contexts.workflows._shared.WorkflowValueObjects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from aef_domain.contexts.workflows.domain.events.WorkflowCreatedEvent import (
    WorkflowCreatedEvent,
)
from aef_domain.contexts.workflows.domain.commands.CreateWorkflowCommand import (
    CreateWorkflowCommand,
)
from aef_domain.contexts.workflows.slices.create_workflow.CreateWorkflowHandler import (
    CreateWorkflowHandler,
)

if TYPE_CHECKING:
    from event_sourcing import EventEnvelope


# === Test Fixtures ===


def create_test_command(
    aggregate_id: str | None = None,
    name: str = "Test Workflow",
) -> CreateWorkflowCommand:
    """Create a test command with default values."""
    return CreateWorkflowCommand(
        aggregate_id=aggregate_id,
        name=name,
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
            ),
        ],
    )


# === In-Memory Test Doubles ===


class InMemoryWorkflowRepository:
    """In-memory repository for testing."""

    def __init__(self) -> None:
        self.saved_aggregates: list[WorkflowAggregate] = []

    async def save(self, aggregate: WorkflowAggregate) -> None:
        self.saved_aggregates.append(aggregate)


class InMemoryEventPublisher:
    """In-memory event publisher for testing."""

    def __init__(self) -> None:
        self.published_events: list[EventEnvelope[WorkflowCreatedEvent]] = []

    async def publish(self, events: list[EventEnvelope[WorkflowCreatedEvent]]) -> None:
        self.published_events.extend(events)


# === Aggregate Tests ===


@pytest.mark.unit
class TestWorkflowAggregate:
    """Tests for WorkflowAggregate with @command_handler and @event_sourcing_handler."""

    def test_create_workflow_emits_event(self) -> None:
        """Creating a workflow should emit WorkflowCreatedEvent."""
        # Arrange
        aggregate = WorkflowAggregate()
        command = create_test_command()

        # Act - use _handle_command which routes to @command_handler
        aggregate._handle_command(command)

        # Assert
        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        assert events[0].event.event_type == "WorkflowCreated"

    def test_create_workflow_updates_state(self) -> None:
        """Creating a workflow should update aggregate state via @event_sourcing_handler."""
        # Arrange
        aggregate = WorkflowAggregate()
        command = create_test_command(name="My Workflow")

        # Act
        aggregate._handle_command(command)

        # Assert
        assert aggregate.id is not None
        assert aggregate.name == "My Workflow"
        assert aggregate.status == WorkflowStatus.PENDING

    def test_create_workflow_with_provided_id(self) -> None:
        """Creating a workflow with provided ID should use that ID."""
        # Arrange
        aggregate = WorkflowAggregate()
        command = create_test_command(aggregate_id="my-workflow-id")

        # Act
        aggregate._handle_command(command)

        # Assert
        assert aggregate.id == "my-workflow-id"

    def test_create_workflow_generates_id_if_not_provided(self) -> None:
        """Creating a workflow without ID should generate one."""
        # Arrange
        aggregate = WorkflowAggregate()
        command = create_test_command(aggregate_id=None)

        # Act
        aggregate._handle_command(command)

        # Assert
        assert aggregate.id is not None
        assert len(aggregate.id) > 0

    def test_cannot_create_existing_workflow(self) -> None:
        """Cannot create a workflow that already exists."""
        # Arrange
        aggregate = WorkflowAggregate()
        command = create_test_command()
        aggregate._handle_command(command)

        # Act & Assert
        with pytest.raises(ValueError, match="already exists"):
            aggregate._handle_command(command)

    def test_aggregate_type_from_decorator(self) -> None:
        """Aggregate type should be set by @aggregate decorator."""
        # Arrange
        aggregate = WorkflowAggregate()

        # Assert
        assert aggregate.get_aggregate_type() == "Workflow"


# === Handler Tests ===


class TestCreateWorkflowHandler:
    """Tests for CreateWorkflowHandler application service."""

    @pytest.mark.asyncio
    async def test_handler_saves_aggregate(self) -> None:
        """Handler should save the aggregate via repository."""
        # Arrange
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = CreateWorkflowHandler(repository, publisher)
        command = create_test_command()

        # Act
        await handler.handle(command)

        # Assert
        assert len(repository.saved_aggregates) == 1

    @pytest.mark.asyncio
    async def test_handler_publishes_events(self) -> None:
        """Handler should publish domain events for integration."""
        # Arrange
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = CreateWorkflowHandler(repository, publisher)
        command = create_test_command()

        # Act
        await handler.handle(command)

        # Assert
        assert len(publisher.published_events) == 1
        assert publisher.published_events[0].event.event_type == "WorkflowCreated"

    @pytest.mark.asyncio
    async def test_handler_returns_workflow_id(self) -> None:
        """Handler should return the created workflow ID."""
        # Arrange
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = CreateWorkflowHandler(repository, publisher)
        command = create_test_command(aggregate_id="test-id")

        # Act
        result = await handler.handle(command)

        # Assert
        assert result == "test-id"


# === Event Tests ===


class TestWorkflowCreatedEvent:
    """Tests for WorkflowCreatedEvent domain event."""

    def test_event_has_correct_type(self) -> None:
        """Event should have correct event_type from ClassVar."""
        # Arrange & Act
        event = WorkflowCreatedEvent(
            workflow_id="test-id",
            name="Test",
            workflow_type=WorkflowType.RESEARCH,
            classification=WorkflowClassification.SIMPLE,
            repository_url="https://github.com/test/repo",
            repository_ref="main",
            phases=[],
        )

        # Assert
        assert event.event_type == "WorkflowCreated"

    def test_event_is_immutable(self) -> None:
        """Event should be immutable (frozen Pydantic model)."""
        # Arrange
        event = WorkflowCreatedEvent(
            workflow_id="test-id",
            name="Test",
            workflow_type=WorkflowType.RESEARCH,
            classification=WorkflowClassification.SIMPLE,
            repository_url="https://github.com/test/repo",
            repository_ref="main",
            phases=[],
        )

        # Act & Assert - Pydantic v2 frozen models raise ValidationError on mutation
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            event.name = "Changed"
