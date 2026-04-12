"""Tests for the create-workflow slice."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowStatus,
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
    WorkflowTemplateCreatedEvent,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    CreateWorkflowTemplateHandler,
)

if TYPE_CHECKING:
    from event_sourcing import EventEnvelope


# === Test Fixtures ===


def create_test_command(
    aggregate_id: str | None = None,
    name: str = "Test Workflow",
) -> CreateWorkflowTemplateCommand:
    """Create a test command with default values."""
    kwargs: dict[str, object] = {}
    if aggregate_id is not None:
        kwargs["aggregate_id"] = aggregate_id
    return CreateWorkflowTemplateCommand(
        **kwargs,  # type: ignore[arg-type]
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
        self.saved_aggregates: list[WorkflowTemplateAggregate] = []

    async def save(self, aggregate: WorkflowTemplateAggregate) -> None:
        self.saved_aggregates.append(aggregate)


class InMemoryEventPublisher:
    """In-memory event publisher for testing."""

    def __init__(self) -> None:
        self.published_events: list[EventEnvelope[WorkflowTemplateCreatedEvent]] = []

    async def publish(self, events: list[EventEnvelope[WorkflowTemplateCreatedEvent]]) -> None:
        self.published_events.extend(events)


# === Aggregate Tests ===


@pytest.mark.unit
class TestWorkflowTemplateAggregate:
    """Tests for WorkflowTemplateAggregate with @command_handler and @event_sourcing_handler."""

    def test_create_workflow_emits_event(self) -> None:
        """Creating a workflow should emit WorkflowTemplateCreatedEvent."""
        # Arrange
        aggregate = WorkflowTemplateAggregate()
        command = create_test_command()

        # Act - use _handle_command which routes to @command_handler
        aggregate._handle_command(command)

        # Assert
        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        assert events[0].event.event_type == "WorkflowTemplateCreated"

    def test_create_workflow_updates_state(self) -> None:
        """Creating a workflow should update aggregate state via @event_sourcing_handler."""
        # Arrange
        aggregate = WorkflowTemplateAggregate()
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
        aggregate = WorkflowTemplateAggregate()
        command = create_test_command(aggregate_id="my-workflow-id")

        # Act
        aggregate._handle_command(command)

        # Assert
        assert aggregate.id == "my-workflow-id"

    def test_create_workflow_generates_id_if_not_provided(self) -> None:
        """Creating a workflow without ID should generate one."""
        # Arrange
        aggregate = WorkflowTemplateAggregate()
        command = create_test_command()

        # Act
        aggregate._handle_command(command)

        # Assert
        assert aggregate.id is not None
        assert len(aggregate.id) > 0

    def test_cannot_create_existing_workflow(self) -> None:
        """Cannot create a workflow that already exists."""
        # Arrange
        aggregate = WorkflowTemplateAggregate()
        command = create_test_command()
        aggregate._handle_command(command)

        # Act & Assert
        with pytest.raises(ValueError, match="already exists"):
            aggregate._handle_command(command)

    def test_aggregate_type_from_decorator(self) -> None:
        """Aggregate type should be set by @aggregate decorator."""
        # Arrange
        aggregate = WorkflowTemplateAggregate()

        # Assert
        assert aggregate.get_aggregate_type() == "WorkflowTemplate"


# === Handler Tests ===


class TestCreateWorkflowTemplateHandler:
    """Tests for CreateWorkflowTemplateHandler application service."""

    @pytest.mark.asyncio
    async def test_handler_saves_aggregate(self) -> None:
        """Handler should save the aggregate via repository."""
        # Arrange
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = CreateWorkflowTemplateHandler(repository, publisher)
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
        handler = CreateWorkflowTemplateHandler(repository, publisher)
        command = create_test_command()

        # Act
        await handler.handle(command)

        # Assert
        assert len(publisher.published_events) == 1
        assert publisher.published_events[0].event.event_type == "WorkflowTemplateCreated"

    @pytest.mark.asyncio
    async def test_handler_returns_workflow_id(self) -> None:
        """Handler should return the created workflow ID."""
        # Arrange
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = CreateWorkflowTemplateHandler(repository, publisher)
        command = create_test_command(aggregate_id="test-id")

        # Act
        result = await handler.handle(command)

        # Assert
        assert result == "test-id"


# === requires_repos Regression Tests (ADR-058 #666) ===


@pytest.mark.unit
class TestRequiresRepos:
    """Regression tests for the requires_repos execution gate."""

    def test_default_requires_repos_is_true(self) -> None:
        """New aggregates default to requires_repos=True (backward compat)."""
        aggregate = WorkflowTemplateAggregate()
        command = create_test_command()
        aggregate._handle_command(command)
        assert aggregate.requires_repos is True

    def test_requires_repos_false_propagates(self) -> None:
        """Setting requires_repos=False on command propagates to aggregate."""
        aggregate = WorkflowTemplateAggregate()
        command = CreateWorkflowTemplateCommand(
            name="Research Task",
            workflow_type=WorkflowType.RESEARCH,
            classification=WorkflowClassification.SIMPLE,
            repository_url="",
            phases=[
                PhaseDefinition(
                    phase_id="phase-1",
                    name="Research",
                    order=1,
                ),
            ],
            requires_repos=False,
        )
        aggregate._handle_command(command)
        assert aggregate.requires_repos is False

    def test_requires_repos_in_emitted_event(self) -> None:
        """requires_repos value should be present in the emitted event."""
        aggregate = WorkflowTemplateAggregate()
        command = CreateWorkflowTemplateCommand(
            name="No Repos Needed",
            workflow_type=WorkflowType.RESEARCH,
            classification=WorkflowClassification.SIMPLE,
            repository_url="",
            phases=[
                PhaseDefinition(
                    phase_id="phase-1",
                    name="Phase 1",
                    order=1,
                ),
            ],
            requires_repos=False,
        )
        aggregate._handle_command(command)
        events = aggregate.get_uncommitted_events()
        event_data = events[0].event.model_dump()
        assert event_data["requires_repos"] is False

    def test_backward_compat_old_events_default_true(self) -> None:
        """Old events without requires_repos field should default to True on rehydration."""
        aggregate = WorkflowTemplateAggregate()
        # Simulate rehydrating from an old event that lacks requires_repos
        old_event_data = {
            "workflow_id": "legacy-wf",
            "name": "Legacy Workflow",
            "workflow_type": "custom",
            "classification": "standard",
            "repository_url": "https://github.com/test/repo",
            "repository_ref": "main",
            "phases": [{"phase_id": "p1", "name": "Phase 1", "order": 1}],
            # No requires_repos field -- simulates pre-#666 events
        }

        class FakeEvent:
            """Simulate a GenericDomainEvent from the gRPC event store."""

            def __init__(self, data: dict) -> None:
                self._data = data

            def model_dump(self) -> dict:
                return dict(self._data)

        aggregate._initialize("legacy-wf")
        aggregate.on_workflow_created(FakeEvent(old_event_data))  # type: ignore[arg-type]
        assert aggregate.requires_repos is True

    def test_repository_url_optional_on_command(self) -> None:
        """repository_url should default to empty string when not provided."""
        command = CreateWorkflowTemplateCommand(
            name="Bare Workflow",
            workflow_type=WorkflowType.RESEARCH,
            classification=WorkflowClassification.SIMPLE,
            phases=[
                PhaseDefinition(
                    phase_id="phase-1",
                    name="Phase 1",
                    order=1,
                ),
            ],
            requires_repos=False,
        )
        assert command.repository_url == ""


# === Event Tests ===


class TestWorkflowTemplateCreatedEvent:
    """Tests for WorkflowTemplateCreatedEvent domain event."""

    def test_event_has_correct_type(self) -> None:
        """Event should have correct event_type from ClassVar."""
        # Arrange & Act
        event = WorkflowTemplateCreatedEvent(
            workflow_id="test-id",
            name="Test",
            workflow_type=WorkflowType.RESEARCH,
            classification=WorkflowClassification.SIMPLE,
            repository_url="https://github.com/test/repo",
            repository_ref="main",
            phases=[],
        )

        # Assert
        assert event.event_type == "WorkflowTemplateCreated"

    def test_event_is_immutable(self) -> None:
        """Event should be immutable (frozen Pydantic model)."""
        # Arrange
        event = WorkflowTemplateCreatedEvent(
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
