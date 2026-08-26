"""Tests for the create-workflow slice."""

from __future__ import annotations

import asyncio
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
        assert result.workflow_id == "test-id"
        assert result.changed is True


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
        outcome = await handler.handle(
            create_test_command(aggregate_id="code-review", name="Code Review v2")
        )

        assert outcome.workflow_id == "code-review"
        assert outcome.changed is True
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


@pytest.mark.unit
class TestProvenanceCannotBeStripped:
    """An install must not erase provenance the template already carries.

    Found in cross-model review of #822. Without these guards the digest
    check is bypassed by declaring nothing: same_version goes false, the
    update is accepted, and version and digest are overwritten with None, so
    a republished package installs cleanly afterwards.
    """

    @pytest.mark.asyncio
    async def test_install_without_version_over_versioned_template_is_refused(self) -> None:
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.errors import (
            WorkflowTemplateProvenanceStrippedError,
        )

        repository = InMemoryWorkflowRepository()
        handler = CreateWorkflowTemplateHandler(repository, InMemoryEventPublisher())
        await handler.handle(
            create_test_command(aggregate_id="code-review", version="0.3.0", source_digest="aaa111")
        )

        with pytest.raises(WorkflowTemplateProvenanceStrippedError, match="no version"):
            await handler.handle(create_test_command(aggregate_id="code-review"))

        aggregate = await repository.get_by_id("code-review")
        assert aggregate is not None
        assert aggregate.package_version == "0.3.0"
        assert aggregate.source_digest == "aaa111"

    @pytest.mark.asyncio
    async def test_install_without_digest_over_digested_template_is_refused(self) -> None:
        """0.3.0/aaa -> 0.4.0/None is a real upgrade that still drops the evidence."""
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.errors import (
            WorkflowTemplateProvenanceStrippedError,
        )

        repository = InMemoryWorkflowRepository()
        handler = CreateWorkflowTemplateHandler(repository, InMemoryEventPublisher())
        await handler.handle(
            create_test_command(aggregate_id="code-review", version="0.3.0", source_digest="aaa111")
        )

        with pytest.raises(WorkflowTemplateProvenanceStrippedError, match="no source digest"):
            await handler.handle(create_test_command(aggregate_id="code-review", version="0.4.0"))

        aggregate = await repository.get_by_id("code-review")
        assert aggregate is not None
        assert aggregate.source_digest == "aaa111"

    @pytest.mark.asyncio
    async def test_force_does_not_permit_stripping(self) -> None:
        """force means overwrite this version on purpose, not drop the evidence."""
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.errors import (
            WorkflowTemplateProvenanceStrippedError,
        )

        repository = InMemoryWorkflowRepository()
        handler = CreateWorkflowTemplateHandler(repository, InMemoryEventPublisher())
        await handler.handle(
            create_test_command(aggregate_id="code-review", version="0.3.0", source_digest="aaa111")
        )

        with pytest.raises(WorkflowTemplateProvenanceStrippedError):
            await handler.handle(create_test_command(aggregate_id="code-review", force=True))

    @pytest.mark.asyncio
    async def test_unversioned_template_stays_installable_without_version(self) -> None:
        """None -> None is the manual/unversioned path and must keep working."""
        repository = InMemoryWorkflowRepository()
        handler = CreateWorkflowTemplateHandler(repository, InMemoryEventPublisher())

        await handler.handle(create_test_command(aggregate_id="manual-wf"))
        await handler.handle(create_test_command(aggregate_id="manual-wf", name="Edited"))

        aggregate = await repository.get_by_id("manual-wf")
        assert aggregate is not None
        assert aggregate.name == "Edited"

    @pytest.mark.asyncio
    async def test_unversioned_template_can_adopt_a_version(self) -> None:
        """None -> declared is the legacy migration path and must be allowed."""
        repository = InMemoryWorkflowRepository()
        handler = CreateWorkflowTemplateHandler(repository, InMemoryEventPublisher())

        await handler.handle(create_test_command(aggregate_id="code-review"))
        await handler.handle(
            create_test_command(aggregate_id="code-review", version="0.3.0", source_digest="aaa111")
        )

        aggregate = await repository.get_by_id("code-review")
        assert aggregate is not None
        assert aggregate.package_version == "0.3.0"


@pytest.mark.unit
class TestArchiveStateAcrossReplay:
    """Archive state must follow the latest lifecycle event, whichever it is.

    Found in cross-model review of #822: only WorkflowTemplateUpdated cleared
    the flag, so a stream ending in a full-definition Created event replayed
    to the latest definition while still marked archived.
    """

    def test_created_after_archived_replays_as_active(self) -> None:
        from syn_domain.contexts.orchestration.domain.commands.ArchiveWorkflowTemplateCommand import (
            ArchiveWorkflowTemplateCommand,
        )

        aggregate = WorkflowTemplateAggregate()
        aggregate._handle_command(create_test_command(aggregate_id="code-review"))
        aggregate.archive_workflow(ArchiveWorkflowTemplateCommand(workflow_id="code-review"))
        assert aggregate.is_archived is True

        replayed = WorkflowTemplateAggregate()
        replayed.rehydrate(aggregate.get_uncommitted_events())
        assert replayed.is_archived is True

        # A later full-definition event reactivates, whichever event it is.
        replayed._apply_definition(aggregate.get_uncommitted_events()[0].event)
        assert replayed.is_archived is False

    def test_archive_still_wins_when_it_is_the_last_event(self) -> None:
        from syn_domain.contexts.orchestration.domain.commands.ArchiveWorkflowTemplateCommand import (
            ArchiveWorkflowTemplateCommand,
        )

        aggregate = WorkflowTemplateAggregate()
        aggregate._handle_command(create_test_command(aggregate_id="code-review"))
        aggregate.archive_workflow(ArchiveWorkflowTemplateCommand(workflow_id="code-review"))

        replayed = WorkflowTemplateAggregate()
        replayed.rehydrate(aggregate.get_uncommitted_events())
        assert replayed.is_archived is True


class BarrieredWorkflowRepository(InMemoryWorkflowRepository):
    """Repository that forces two callers to observe the same snapshot.

    WHY: load-or-create is only race-safe because the append is guarded by
    optimistic concurrency, and a plain fake never exercises that. Its async
    methods contain no suspension point, so even asyncio.gather serializes
    them and both installs succeed. This barrier holds the first N loaders
    until all of them have read, which is what produces the interleaving that
    matters: load-load-save-save.
    """

    def __init__(self, participants: int) -> None:
        super().__init__()
        self._barrier = asyncio.Barrier(participants)

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        loaded = await super().get_by_id(aggregate_id)
        await self._barrier.wait()
        return loaded


@pytest.mark.unit
class TestConcurrentInstall:
    """A genuine concurrent double-install must lose exactly one writer.

    Requested in cross-model review of #822.
    """

    @pytest.mark.asyncio
    async def test_concurrent_first_install_commits_exactly_one_event(self) -> None:
        from event_sourcing import ConcurrencyConflictError

        repository = BarrieredWorkflowRepository(participants=2)
        publisher = InMemoryEventPublisher()
        handler = CreateWorkflowTemplateHandler(repository, publisher)

        results = await asyncio.gather(
            handler.handle(create_test_command(aggregate_id="code-review", name="A")),
            handler.handle(create_test_command(aggregate_id="code-review", name="B")),
            return_exceptions=True,
        )

        succeeded = [r for r in results if not isinstance(r, BaseException)]
        conflicted = [r for r in results if isinstance(r, ConcurrencyConflictError)]
        assert len(succeeded) == 1
        assert len(conflicted) == 1

        # The loser must not have half-committed: one event on the stream.
        assert len(repository.streams["code-review"]) == 1

    @pytest.mark.asyncio
    async def test_concurrent_reinstall_commits_exactly_one_update(self) -> None:
        from event_sourcing import ConcurrencyConflictError

        repository = BarrieredWorkflowRepository(participants=2)
        handler = CreateWorkflowTemplateHandler(repository, InMemoryEventPublisher())

        # Seed the stream. This install passes the barrier alone, so it needs
        # its own participant count of one.
        seed_repo_barrier = repository._barrier
        repository._barrier = asyncio.Barrier(1)
        await handler.handle(create_test_command(aggregate_id="code-review"))
        repository._barrier = seed_repo_barrier

        results = await asyncio.gather(
            handler.handle(create_test_command(aggregate_id="code-review", name="A")),
            handler.handle(create_test_command(aggregate_id="code-review", name="B")),
            return_exceptions=True,
        )

        succeeded = [r for r in results if not isinstance(r, BaseException)]
        conflicted = [r for r in results if isinstance(r, ConcurrencyConflictError)]
        assert len(succeeded) == 1
        assert len(conflicted) == 1

        # Created plus exactly one Updated - the loser committed nothing.
        assert len(repository.streams["code-review"]) == 2


@pytest.mark.unit
class TestInstallIsIdempotent:
    """A byte-identical reinstall succeeds and writes nothing (issue #822).

    The issue title is "install is not idempotent". Refusing an identical
    reinstall with a nicer error is still not idempotent: it exits non-zero,
    it breaks retry after a partly-failed multi-workflow install, and it
    trains users to reach for --force, which is the flag that disables the
    republish check.
    """

    @pytest.mark.asyncio
    async def test_identical_reinstall_is_a_successful_no_op(self) -> None:
        repository = InMemoryWorkflowRepository()
        handler = CreateWorkflowTemplateHandler(repository, InMemoryEventPublisher())
        command = create_test_command(
            aggregate_id="code-review", version="0.3.0", source_digest="aaa111"
        )

        first = await handler.handle(command)
        second = await handler.handle(command)

        assert first.changed is True
        assert second.changed is False
        assert second.workflow_id == "code-review"

    @pytest.mark.asyncio
    async def test_identical_reinstall_writes_no_event(self) -> None:
        """Stronger than overwriting quietly: nothing is appended at all."""
        repository = InMemoryWorkflowRepository()
        handler = CreateWorkflowTemplateHandler(repository, InMemoryEventPublisher())
        command = create_test_command(
            aggregate_id="code-review", version="0.3.0", source_digest="aaa111"
        )

        await handler.handle(command)
        await handler.handle(command)

        assert len(repository.streams["code-review"]) == 1

    @pytest.mark.asyncio
    async def test_matching_version_without_digests_still_refuses(self) -> None:
        """No digest on either side proves nothing, so it fails safe."""
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.errors import (
            WorkflowTemplateVersionAlreadyInstalledError,
        )

        repository = InMemoryWorkflowRepository()
        handler = CreateWorkflowTemplateHandler(repository, InMemoryEventPublisher())
        command = create_test_command(aggregate_id="code-review", version="0.3.0")

        await handler.handle(command)

        with pytest.raises(WorkflowTemplateVersionAlreadyInstalledError):
            await handler.handle(command)

    @pytest.mark.asyncio
    async def test_changed_digest_still_refuses_loudly(self) -> None:
        """The security lives here, and the no-op path must not weaken it."""
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.errors import (
            WorkflowTemplateDigestMismatchError,
        )

        repository = InMemoryWorkflowRepository()
        handler = CreateWorkflowTemplateHandler(repository, InMemoryEventPublisher())
        await handler.handle(
            create_test_command(aggregate_id="code-review", version="0.3.0", source_digest="aaa111")
        )

        with pytest.raises(WorkflowTemplateDigestMismatchError):
            await handler.handle(
                create_test_command(
                    aggregate_id="code-review", version="0.3.0", source_digest="bbb222"
                )
            )

    @pytest.mark.asyncio
    async def test_retry_after_partial_failure_gets_past_the_installed_one(self) -> None:
        """The case that motivated this: A succeeded, B failed, user retries.

        Under the refusal behaviour the retry died on A before ever reaching
        B, and the only way through was --force.
        """
        repository = InMemoryWorkflowRepository()
        handler = CreateWorkflowTemplateHandler(repository, InMemoryEventPublisher())

        wf_a = create_test_command(aggregate_id="wf-a", version="0.3.0", source_digest="aaa111")
        wf_b = create_test_command(aggregate_id="wf-b", version="0.3.0", source_digest="aaa111")

        await handler.handle(wf_a)  # first attempt: A lands, B "fails" (not sent)

        # Retry the whole package. A must not block B.
        retry_a = await handler.handle(wf_a)
        retry_b = await handler.handle(wf_b)

        assert retry_a.changed is False
        assert retry_b.changed is True
