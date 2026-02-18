"""Tests for Artifact aggregate and value objects.

Tests cover:
- Artifact creation
- Content hashing and size calculation
- Artifact lineage (derived_from)
- Event sourcing behavior
"""

import pytest

from syn_domain.contexts.artifacts import (
    ArtifactAggregate,
    ArtifactType,
    ContentType,
    CreateArtifactCommand,
    compute_content_hash,
)


@pytest.mark.unit
class TestComputeContentHash:
    """Tests for content hashing."""

    def test_hash_content(self) -> None:
        """Test basic content hashing."""
        content = "Hello, World!"
        hash1 = compute_content_hash(content)
        hash2 = compute_content_hash(content)

        # Same content produces same hash
        assert hash1 == hash2
        # Hash is 64 character hex string (SHA-256)
        assert len(hash1) == 64
        assert all(c in "0123456789abcdef" for c in hash1)

    def test_different_content_different_hash(self) -> None:
        """Test that different content produces different hash."""
        hash1 = compute_content_hash("Hello")
        hash2 = compute_content_hash("World")
        assert hash1 != hash2

    def test_empty_string_hash(self) -> None:
        """Test hashing empty string."""
        hash_empty = compute_content_hash("")
        assert len(hash_empty) == 64


class TestArtifactAggregate:
    """Tests for ArtifactAggregate."""

    def test_create_artifact(self) -> None:
        """Test creating a basic artifact."""
        artifact = ArtifactAggregate()

        command = CreateArtifactCommand(
            workflow_id="wf-123",
            phase_id="research",
            artifact_type=ArtifactType.RESEARCH_SUMMARY,
            content="# Research Summary\n\nKey findings...",
            title="AI Agents Research",
        )

        artifact.create_artifact(command)

        assert artifact.id is not None
        assert artifact.workflow_id == "wf-123"
        assert artifact.phase_id == "research"
        assert artifact.artifact_type == ArtifactType.RESEARCH_SUMMARY
        assert artifact.content_type == ContentType.TEXT_MARKDOWN
        assert artifact.content == "# Research Summary\n\nKey findings..."
        assert artifact.title == "AI Agents Research"
        assert artifact.is_primary_deliverable is True
        assert artifact.content_hash is not None
        assert len(artifact.content_hash) == 64
        assert artifact.size_bytes > 0

    def test_create_artifact_with_id(self) -> None:
        """Test creating artifact with provided ID."""
        artifact = ArtifactAggregate()

        command = CreateArtifactCommand(
            aggregate_id="custom-artifact-id",
            workflow_id="wf-123",
            phase_id="research",
            artifact_type=ArtifactType.TEXT,
            content="Some content",
        )

        artifact.create_artifact(command)

        assert str(artifact.id) == "custom-artifact-id"

    def test_create_artifact_with_session(self) -> None:
        """Test creating artifact with session context."""
        artifact = ArtifactAggregate()

        command = CreateArtifactCommand(
            workflow_id="wf-123",
            phase_id="research",
            session_id="sess-456",
            artifact_type=ArtifactType.TEXT,
            content="Session output",
        )

        artifact.create_artifact(command)

        assert artifact.session_id == "sess-456"

    def test_create_artifact_with_execution_id(self) -> None:
        """Test creating artifact with execution_id context (v2).

        The execution_id links artifacts to specific workflow execution runs,
        enabling queries like "get all artifacts from execution X".
        """
        artifact = ArtifactAggregate()

        command = CreateArtifactCommand(
            workflow_id="wf-123",
            phase_id="research",
            execution_id="exec-789",
            session_id="sess-456",
            artifact_type=ArtifactType.TEXT,
            content="Execution output",
        )

        artifact.create_artifact(command)

        assert artifact.execution_id == "exec-789"
        assert artifact.workflow_id == "wf-123"
        assert artifact.phase_id == "research"
        assert artifact.session_id == "sess-456"

    def test_create_artifact_execution_id_optional(self) -> None:
        """Test that execution_id is optional for backward compatibility."""
        artifact = ArtifactAggregate()

        command = CreateArtifactCommand(
            workflow_id="wf-123",
            phase_id="research",
            artifact_type=ArtifactType.TEXT,
            content="No execution context",
        )

        artifact.create_artifact(command)

        assert artifact.execution_id is None  # Defaults to None

    def test_create_artifact_with_lineage(self) -> None:
        """Test creating artifact with derived_from lineage."""
        artifact = ArtifactAggregate()

        command = CreateArtifactCommand(
            workflow_id="wf-123",
            phase_id="planning",
            artifact_type=ArtifactType.PLAN,
            content="# Plan\n\nBased on research...",
            derived_from=["research-artifact-id", "requirements-artifact-id"],
        )

        artifact.create_artifact(command)

        assert artifact.derived_from == ["research-artifact-id", "requirements-artifact-id"]

    def test_create_artifact_not_primary(self) -> None:
        """Test creating non-primary artifact."""
        artifact = ArtifactAggregate()

        command = CreateArtifactCommand(
            workflow_id="wf-123",
            phase_id="research",
            artifact_type=ArtifactType.TEXT,
            content="Supplementary notes",
            is_primary_deliverable=False,
        )

        artifact.create_artifact(command)

        assert artifact.is_primary_deliverable is False

    def test_create_artifact_with_metadata(self) -> None:
        """Test creating artifact with metadata."""
        artifact = ArtifactAggregate()

        command = CreateArtifactCommand(
            workflow_id="wf-123",
            phase_id="research",
            artifact_type=ArtifactType.CODE,
            content="def hello(): pass",
            content_type=ContentType.TEXT_PYTHON,
            metadata={"language": "python", "lines": 1},
        )

        artifact.create_artifact(command)

        assert artifact.content_type == ContentType.TEXT_PYTHON

    def test_create_artifact_twice_fails(self) -> None:
        """Test that creating artifact twice raises error."""
        artifact = ArtifactAggregate()
        command = CreateArtifactCommand(
            workflow_id="wf-123",
            phase_id="research",
            artifact_type=ArtifactType.TEXT,
            content="Content",
        )

        artifact.create_artifact(command)

        with pytest.raises(ValueError, match="already exists"):
            artifact.create_artifact(command)

    def test_create_artifact_empty_content_fails(self) -> None:
        """Test that empty content fails validation."""
        with pytest.raises(ValueError):
            CreateArtifactCommand(
                workflow_id="wf-123",
                phase_id="research",
                artifact_type=ArtifactType.TEXT,
                content="",  # Empty content
            )

    def test_content_hash_deterministic(self) -> None:
        """Test that content hash is deterministic."""
        content = "Same content for both artifacts"

        artifact1 = ArtifactAggregate()
        artifact1.create_artifact(
            CreateArtifactCommand(
                workflow_id="wf-1",
                phase_id="p1",
                artifact_type=ArtifactType.TEXT,
                content=content,
            )
        )

        artifact2 = ArtifactAggregate()
        artifact2.create_artifact(
            CreateArtifactCommand(
                workflow_id="wf-2",
                phase_id="p2",
                artifact_type=ArtifactType.TEXT,
                content=content,
            )
        )

        assert artifact1.content_hash == artifact2.content_hash

    def test_size_bytes_calculated(self) -> None:
        """Test that size_bytes is correctly calculated."""
        content = "Hello, World!"  # 13 ASCII characters
        expected_size = len(content.encode("utf-8"))

        artifact = ArtifactAggregate()
        artifact.create_artifact(
            CreateArtifactCommand(
                workflow_id="wf-123",
                phase_id="research",
                artifact_type=ArtifactType.TEXT,
                content=content,
            )
        )

        assert artifact.size_bytes == expected_size

    def test_size_bytes_unicode(self) -> None:
        """Test size_bytes with unicode content."""
        content = "Hello 🌍"  # Emoji is 4 bytes in UTF-8
        expected_size = len(content.encode("utf-8"))

        artifact = ArtifactAggregate()
        artifact.create_artifact(
            CreateArtifactCommand(
                workflow_id="wf-123",
                phase_id="research",
                artifact_type=ArtifactType.TEXT,
                content=content,
            )
        )

        assert artifact.size_bytes == expected_size
        assert artifact.size_bytes > len(content)  # UTF-8 encoding is larger


class TestArtifactEventSourcing:
    """Tests for event sourcing behavior."""

    def test_uncommitted_events(self) -> None:
        """Test that creation produces uncommitted event."""
        artifact = ArtifactAggregate()
        artifact.create_artifact(
            CreateArtifactCommand(
                workflow_id="wf-123",
                phase_id="research",
                artifact_type=ArtifactType.TEXT,
                content="Content",
            )
        )

        events = artifact.get_uncommitted_events()
        assert len(events) == 1
        # Events are wrapped in EventEnvelope, access the event inside
        assert events[0].event.event_type == "ArtifactCreated"

    def test_aggregate_type(self) -> None:
        """Test aggregate type is set correctly."""
        artifact = ArtifactAggregate()
        artifact.create_artifact(
            CreateArtifactCommand(
                workflow_id="wf-123",
                phase_id="research",
                artifact_type=ArtifactType.TEXT,
                content="Content",
            )
        )

        assert artifact.get_aggregate_type() == "Artifact"


class TestArtifactTypes:
    """Tests for artifact type enum."""

    def test_research_types(self) -> None:
        """Test research artifact types exist."""
        assert ArtifactType.RESEARCH_SUMMARY
        assert ArtifactType.ANALYSIS_REPORT

    def test_planning_types(self) -> None:
        """Test planning artifact types exist."""
        assert ArtifactType.PLAN
        assert ArtifactType.REQUIREMENTS
        assert ArtifactType.DESIGN_DOC

    def test_implementation_types(self) -> None:
        """Test implementation artifact types exist."""
        assert ArtifactType.CODE
        assert ArtifactType.CONFIGURATION
        assert ArtifactType.SCRIPT

    def test_documentation_types(self) -> None:
        """Test documentation artifact types exist."""
        assert ArtifactType.DOCUMENTATION
        assert ArtifactType.README
        assert ArtifactType.API_SPEC
