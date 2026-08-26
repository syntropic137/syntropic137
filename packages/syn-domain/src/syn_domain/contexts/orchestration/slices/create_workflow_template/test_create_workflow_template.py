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
    from event_sourcing import DomainEvent, EventEnvelope


# === Test Fixtures ===


def create_test_command(
    aggregate_id: str | None = None,
    name: str = "Test Workflow",
    version: str | None = None,
    source_digest: str | None = None,
    force: bool = False,
) -> CreateWorkflowTemplateCommand:
    """Create a test command with default values."""
    kwargs: dict[str, object] = {}
    if aggregate_id is not None:
        kwargs["aggregate_id"] = aggregate_id
    return CreateWorkflowTemplateCommand(
        **kwargs,  # type: ignore[arg-type]
        name=name,
        version=version,
        source_digest=source_digest,
        force=force,
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
    """In-memory repository for testing.

    Stores event streams and rehydrates on load rather than handing back the
    same object. WHY (issue #822): the reinstall bug lives in the load path,
    so a double that returns the live instance would pass while production
    fails. Replaying the stream is what makes these tests meaningful.
    """

    def __init__(self) -> None:
        self.saved_aggregates: list[WorkflowTemplateAggregate] = []
        self.streams: dict[str, list[EventEnvelope[DomainEvent]]] = {}

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        events = self.streams.get(aggregate_id)
        if not events:
            return None
        aggregate = WorkflowTemplateAggregate()
        aggregate.rehydrate(list(events))
        return aggregate

    async def save(self, aggregate: WorkflowTemplateAggregate) -> None:
        """Append uncommitted events, enforcing optimistic concurrency.

        WHY (issue #822): without this check the double accepts a fresh
        aggregate saved over an existing stream, so a reinstall test would
        pass here while production raised "expected version 0, got 1". The
        check is what makes these tests able to fail.
        """
        from event_sourcing import ConcurrencyConflictError

        stream_id = str(aggregate.id)
        existing = self.streams.setdefault(stream_id, [])
        uncommitted = aggregate.get_uncommitted_events()
        expected_base = aggregate.version - len(uncommitted)
        if expected_base != len(existing):
            raise ConcurrencyConflictError(
                expected_version=expected_base,
                actual_version=len(existing),
            )

        self.saved_aggregates.append(aggregate)
        existing.extend(uncommitted)


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


# === Reinstall / Upsert Regression Tests (issue #822) ===


@pytest.mark.unit
class TestReinstallIsIdempotent:
    """Installing the same package twice must not fail with a store internal.

    WHY these exist: every single-install test passed while the second install
    of any plugin returned "Concurrency conflict: expected version 0, got 1".
    The bug class is invisible unless a test installs twice, so these tests
    install twice.
    """

    @pytest.mark.asyncio
    async def test_second_install_of_same_id_does_not_raise_concurrency_conflict(
        self,
    ) -> None:
        """The original P0: a second install of a package id blew up."""
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = CreateWorkflowTemplateHandler(repository, publisher)

        await handler.handle(create_test_command(aggregate_id="code-review"))
        # Second install with no version declared: plain upsert, no refusal.
        workflow_id = await handler.handle(
            create_test_command(aggregate_id="code-review", name="Code Review v2")
        )

        assert workflow_id == "code-review"
        aggregate = await repository.get_by_id("code-review")
        assert aggregate is not None
        assert aggregate.name == "Code Review v2"

    @pytest.mark.asyncio
    async def test_second_install_emits_updated_not_created(self) -> None:
        """The stream holds Created -> Updated, which is what preserves provenance."""
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = CreateWorkflowTemplateHandler(repository, publisher)

        await handler.handle(create_test_command(aggregate_id="code-review"))
        await handler.handle(create_test_command(aggregate_id="code-review"))

        event_types = [e.event.event_type for e in publisher.published_events]
        assert event_types == ["WorkflowTemplateCreated", "WorkflowTemplateUpdated"]

    @pytest.mark.asyncio
    async def test_reinstalling_same_version_is_refused_without_force(self) -> None:
        """No silent overwrite: a matching version needs explicit intent."""
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.errors import (
            WorkflowTemplateVersionAlreadyInstalledError,
        )

        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = CreateWorkflowTemplateHandler(repository, publisher)
        command = create_test_command(aggregate_id="code-review", version="0.3.0")

        await handler.handle(command)

        with pytest.raises(WorkflowTemplateVersionAlreadyInstalledError, match="already installed"):
            await handler.handle(command)

    @pytest.mark.asyncio
    async def test_force_reinstalls_a_matching_version(self) -> None:
        """--force is the escape hatch that performs the upsert."""
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = CreateWorkflowTemplateHandler(repository, publisher)

        await handler.handle(create_test_command(aggregate_id="code-review", version="0.3.0"))
        await handler.handle(
            create_test_command(
                aggregate_id="code-review",
                name="Code Review forced",
                version="0.3.0",
                force=True,
            )
        )

        aggregate = await repository.get_by_id("code-review")
        assert aggregate is not None
        assert aggregate.name == "Code Review forced"

    @pytest.mark.asyncio
    async def test_installing_a_newer_version_upserts_without_force(self) -> None:
        """A genuine upgrade is the common case and must not need a flag."""
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = CreateWorkflowTemplateHandler(repository, publisher)

        await handler.handle(create_test_command(aggregate_id="code-review", version="0.3.0"))
        await handler.handle(
            create_test_command(aggregate_id="code-review", name="Newer", version="0.4.0")
        )

        aggregate = await repository.get_by_id("code-review")
        assert aggregate is not None
        assert aggregate.name == "Newer"
        assert aggregate.package_version == "0.4.0"

    @pytest.mark.asyncio
    async def test_same_version_different_digest_is_refused_loudly(self) -> None:
        """Republished content under an unchanged version must not pass silently.

        A version check alone would treat this as "already installed" and skip
        it, which is exactly what a supply-chain republish wants.
        """
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.errors import (
            WorkflowTemplateDigestMismatchError,
        )

        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = CreateWorkflowTemplateHandler(repository, publisher)

        await handler.handle(
            create_test_command(aggregate_id="code-review", version="0.3.0", source_digest="aaa111")
        )

        with pytest.raises(WorkflowTemplateDigestMismatchError, match="different source"):
            await handler.handle(
                create_test_command(
                    aggregate_id="code-review", version="0.3.0", source_digest="bbb222"
                )
            )

    @pytest.mark.asyncio
    async def test_reinstall_after_archive_restores_the_template(self) -> None:
        """The data-loss path: a destructive update archived, then could not recreate.

        Install must be able to bring an archived template back, otherwise a
        failed update leaves the user with nothing.
        """
        from syn_domain.contexts.orchestration.domain.commands.ArchiveWorkflowTemplateCommand import (
            ArchiveWorkflowTemplateCommand,
        )

        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = CreateWorkflowTemplateHandler(repository, publisher)

        await handler.handle(create_test_command(aggregate_id="code-review"))

        archived = await repository.get_by_id("code-review")
        assert archived is not None
        archived.archive_workflow(ArchiveWorkflowTemplateCommand(workflow_id="code-review"))
        await repository.save(archived)

        stale = await repository.get_by_id("code-review")
        assert stale is not None
        assert stale.is_archived is True

        await handler.handle(create_test_command(aggregate_id="code-review", name="Restored"))

        restored = await repository.get_by_id("code-review")
        assert restored is not None
        assert restored.is_archived is False
        assert restored.name == "Restored"
