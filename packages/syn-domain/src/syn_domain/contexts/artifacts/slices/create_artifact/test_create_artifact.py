"""Tests for CreateArtifact handler - VSA compliance."""

from __future__ import annotations

import pytest

from syn_domain.contexts.artifacts.domain.commands.CreateArtifactCommand import (
    CreateArtifactCommand,
)

from .CreateArtifactHandler import CreateArtifactHandler


@pytest.mark.unit
def test_handler_exists() -> None:
    """VSA requires handler exists."""
    assert CreateArtifactHandler is not None


@pytest.mark.unit
def test_command_exists() -> None:
    """VSA requires command exists."""
    assert CreateArtifactCommand is not None


@pytest.mark.unit
def test_handler_can_be_instantiated() -> None:
    """Handler can be instantiated with repository."""

    class MockRepository:
        """Mock repository for testing."""

        def save(self, aggregate: object) -> None:
            """Mock save method."""
            pass

    repo = MockRepository()
    handler = CreateArtifactHandler(repo)
    assert handler is not None
    assert handler.repository is repo


@pytest.mark.unit
def test_command_has_required_fields() -> None:
    """Command has required fields for artifact creation."""
    from syn_domain.contexts.artifacts._shared.value_objects import ArtifactType

    # Create command with minimal required fields
    command = CreateArtifactCommand(
        workflow_id="test-workflow",
        phase_id="test-phase",
        artifact_type=ArtifactType.DOCUMENTATION,
        content="Test content",
    )

    assert command.workflow_id == "test-workflow"
    assert command.phase_id == "test-phase"
    assert command.artifact_type == ArtifactType.DOCUMENTATION
    assert command.content == "Test content"


# TODO(#55): Add integration tests with real repository
# TODO(#55): Add tests for validation logic (duplicate ID, missing content)
# TODO(#55): Add tests for content hash computation


class TestArtifactCreatedAt:
    """#920: an artifact must record WHEN it was created.

    Before v4 the event carried no timestamp. ``DomainEvent`` declares none,
    and projection handlers receive a flat payload rather than the envelope,
    so ``event_data.get("created_at")`` returned None for every artifact ever
    created. Two visible symptoms, one cause: the CLI's ``Created`` column read
    ``-`` on every row, and ``ListArtifactsQuery`` - which already defaults to
    ``-created_at`` - had nothing to sort on, so ordering degraded to insertion
    order and a just-created artifact appeared on the LAST page.
    """

    def test_created_artifact_records_its_creation_time(self) -> None:
        """The emitted event carries a timezone-aware UTC timestamp."""
        from datetime import UTC, datetime

        from syn_domain.contexts.artifacts._shared.value_objects import ArtifactType
        from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
            ArtifactAggregate,
        )
        from syn_domain.contexts.artifacts.domain.commands.CreateArtifactCommand import (
            CreateArtifactCommand,
        )

        before = datetime.now(UTC)
        aggregate = ArtifactAggregate()
        aggregate.create_artifact(
            CreateArtifactCommand(
                workflow_id="wf-1",
                phase_id="p-1",
                artifact_type=ArtifactType.ANALYSIS_REPORT,
                content="probe",
            )
        )
        after = datetime.now(UTC)

        envelopes = aggregate.get_uncommitted_events()
        assert envelopes, "creating an artifact must emit an event"
        created = envelopes[0].event

        # The assertion that would have failed before v4: the field existed on
        # the read model and was never populated, so this was always None.
        assert created.created_at is not None, (
            "ArtifactCreatedEvent must state when it happened; nothing "
            "downstream can recover the time otherwise (#920)"
        )
        assert created.created_at.tzinfo is not None, "must be timezone-aware"
        assert before <= created.created_at <= after
