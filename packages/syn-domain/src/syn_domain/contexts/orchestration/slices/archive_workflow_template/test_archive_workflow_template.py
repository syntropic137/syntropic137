"""Tests for the archive-workflow-template slice."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.ArchiveWorkflowTemplateCommand import (
    ArchiveWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateArchivedEvent import (
    WorkflowTemplateArchivedEvent,
)
from syn_domain.contexts.orchestration.slices.archive_workflow_template.ArchiveWorkflowTemplateHandler import (
    ArchiveWorkflowTemplateHandler,
)

# === Helpers ===


def _create_aggregate(workflow_id: str = "wf-test-123") -> WorkflowTemplateAggregate:
    """Create a WorkflowTemplateAggregate with a single phase."""
    aggregate = WorkflowTemplateAggregate()
    command = CreateWorkflowTemplateCommand(
        aggregate_id=workflow_id,
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
            ),
        ],
    )
    aggregate._handle_command(command)
    aggregate.mark_events_as_committed()
    return aggregate


# === In-Memory Test Doubles ===


class InMemoryWorkflowRepository:
    """In-memory repository for testing."""

    def __init__(self) -> None:
        self._aggregates: dict[str, WorkflowTemplateAggregate] = {}

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        return self._aggregates.get(aggregate_id)

    async def save(self, aggregate: WorkflowTemplateAggregate) -> None:
        aggregate_id = str(aggregate.id)
        self._aggregates[aggregate_id] = aggregate

    def seed(self, aggregate: WorkflowTemplateAggregate) -> None:
        """Seed a pre-built aggregate for testing."""
        self._aggregates[str(aggregate.id)] = aggregate


@dataclass(frozen=True)
class FakeExecutionSummary:
    """Minimal execution summary for testing."""

    status: str


class InMemoryExecutionProjection:
    """In-memory execution projection for testing."""

    def __init__(self) -> None:
        self._executions: dict[str, list[FakeExecutionSummary]] = {}

    async def get_by_workflow_id(self, workflow_id: str) -> list[FakeExecutionSummary]:
        return self._executions.get(workflow_id, [])

    def seed(self, workflow_id: str, statuses: list[str]) -> None:
        """Seed executions for a workflow."""
        self._executions[workflow_id] = [FakeExecutionSummary(status=s) for s in statuses]


# === Aggregate Tests ===


@pytest.mark.unit
class TestWorkflowTemplateArchive:
    """Tests for archive command/event on WorkflowTemplateAggregate."""

    def test_archive_workflow_emits_event(self) -> None:
        """Archiving a workflow should emit WorkflowTemplateArchivedEvent."""
        aggregate = _create_aggregate()
        command = ArchiveWorkflowTemplateCommand(workflow_id="wf-test-123", archived_by="test")

        aggregate._handle_command(command)

        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        assert events[0].event.event_type == "WorkflowTemplateArchived"

    def test_archive_workflow_updates_state(self) -> None:
        """After archive, aggregate.is_archived should be True."""
        aggregate = _create_aggregate()
        command = ArchiveWorkflowTemplateCommand(workflow_id="wf-test-123")

        aggregate._handle_command(command)

        assert aggregate.is_archived is True

    def test_cannot_archive_already_archived(self) -> None:
        """Archiving an already-archived workflow raises ValueError."""
        aggregate = _create_aggregate()
        command = ArchiveWorkflowTemplateCommand(workflow_id="wf-test-123")
        aggregate._handle_command(command)
        aggregate.mark_events_as_committed()

        with pytest.raises(ValueError, match="already archived"):
            aggregate._handle_command(command)

    def test_archive_event_is_immutable(self) -> None:
        """WorkflowTemplateArchivedEvent should be frozen."""
        from pydantic import ValidationError

        event = WorkflowTemplateArchivedEvent(
            workflow_id="wf-test-123",
            archived_by="test",
        )

        with pytest.raises(ValidationError):
            event.workflow_id = "changed"  # type: ignore[misc]


# === Handler Tests ===


@pytest.mark.unit
class TestArchiveWorkflowTemplateHandler:
    """Tests for ArchiveWorkflowTemplateHandler application service."""

    @pytest.mark.asyncio
    async def test_handler_archives_workflow(self) -> None:
        """Happy path: no active executions, handler returns success."""
        repo = InMemoryWorkflowRepository()
        repo.seed(_create_aggregate())
        projection = InMemoryExecutionProjection()

        handler = ArchiveWorkflowTemplateHandler(repository=repo, execution_projection=projection)
        command = ArchiveWorkflowTemplateCommand(workflow_id="wf-test-123")
        result = await handler.handle(command)

        assert result is not None
        assert result.success is True

    @pytest.mark.asyncio
    async def test_handler_rejects_with_active_executions(self) -> None:
        """Running executions should block archiving."""
        repo = InMemoryWorkflowRepository()
        repo.seed(_create_aggregate())
        projection = InMemoryExecutionProjection()
        projection.seed("wf-test-123", ["running"])

        handler = ArchiveWorkflowTemplateHandler(repository=repo, execution_projection=projection)
        command = ArchiveWorkflowTemplateCommand(workflow_id="wf-test-123")
        result = await handler.handle(command)

        assert result is not None
        assert result.success is False
        assert "active execution" in result.error.lower()

    @pytest.mark.asyncio
    async def test_handler_rejects_with_paused_executions(self) -> None:
        """Paused executions count as active and should block archiving."""
        repo = InMemoryWorkflowRepository()
        repo.seed(_create_aggregate())
        projection = InMemoryExecutionProjection()
        projection.seed("wf-test-123", ["paused"])

        handler = ArchiveWorkflowTemplateHandler(repository=repo, execution_projection=projection)
        command = ArchiveWorkflowTemplateCommand(workflow_id="wf-test-123")
        result = await handler.handle(command)

        assert result is not None
        assert result.success is False

    @pytest.mark.asyncio
    async def test_handler_allows_with_completed_executions(self) -> None:
        """Completed/failed/cancelled executions should NOT block archiving."""
        repo = InMemoryWorkflowRepository()
        repo.seed(_create_aggregate())
        projection = InMemoryExecutionProjection()
        projection.seed("wf-test-123", ["completed", "failed", "cancelled"])

        handler = ArchiveWorkflowTemplateHandler(repository=repo, execution_projection=projection)
        command = ArchiveWorkflowTemplateCommand(workflow_id="wf-test-123")
        result = await handler.handle(command)

        assert result is not None
        assert result.success is True

    @pytest.mark.asyncio
    async def test_handler_returns_none_for_missing_workflow(self) -> None:
        """Handler returns None when workflow is not found."""
        repo = InMemoryWorkflowRepository()
        projection = InMemoryExecutionProjection()

        handler = ArchiveWorkflowTemplateHandler(repository=repo, execution_projection=projection)
        command = ArchiveWorkflowTemplateCommand(workflow_id="nonexistent")
        result = await handler.handle(command)

        assert result is None
