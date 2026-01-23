"""Tests for CreateArtifact handler - VSA compliance."""

from __future__ import annotations

import pytest

from aef_domain.contexts.artifacts.domain.commands.CreateArtifactCommand import (
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
    from aef_domain.contexts.artifacts._shared.value_objects import ArtifactType

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
