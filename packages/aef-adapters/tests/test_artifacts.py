"""Tests for artifact bundle model."""

from __future__ import annotations

from pathlib import Path

import pytest

from aef_adapters.artifacts import (
    ArtifactBundle,
    ArtifactFile,
    ArtifactMetadata,
    PhaseContext,
)
from aef_adapters.artifacts.bundle import ArtifactType

# ============================================================================
# Test ArtifactMetadata
# ============================================================================


@pytest.mark.unit
class TestArtifactMetadata:
    """Tests for ArtifactMetadata dataclass."""

    def test_create_default_metadata(self) -> None:
        """Test creating metadata with defaults."""
        metadata = ArtifactMetadata()

        assert metadata.workflow_id is None
        assert metadata.phase_id is None
        assert metadata.artifact_type == ArtifactType.OTHER
        assert metadata.is_primary is False
        assert metadata.derived_from == ()

    def test_create_full_metadata(self) -> None:
        """Test creating metadata with all fields."""
        metadata = ArtifactMetadata(
            workflow_id="wf-123",
            phase_id="phase-research",
            session_id="session-456",
            artifact_type=ArtifactType.RESEARCH_SUMMARY,
            title="Research Findings",
            description="Summary of research phase",
            is_primary=True,
            derived_from=("parent-1", "parent-2"),
            extra={"custom_key": "custom_value"},
        )

        assert metadata.workflow_id == "wf-123"
        assert metadata.phase_id == "phase-research"
        assert metadata.artifact_type == ArtifactType.RESEARCH_SUMMARY
        assert metadata.is_primary is True
        assert metadata.derived_from == ("parent-1", "parent-2")
        assert metadata.extra["custom_key"] == "custom_value"


# ============================================================================
# Test ArtifactFile
# ============================================================================


class TestArtifactFile:
    """Tests for ArtifactFile dataclass."""

    def test_create_artifact_file(self) -> None:
        """Test creating an artifact file."""
        content = b"Hello, World!"
        artifact = ArtifactFile(
            path=Path("hello.txt"),
            content=content,
        )

        assert artifact.path == Path("hello.txt")
        assert artifact.content == content
        assert artifact.size_bytes == 13
        assert artifact.content_hash != ""  # SHA-256 computed
        assert len(artifact.content_hash) == 64  # SHA-256 is 64 hex chars

    def test_text_content_property(self) -> None:
        """Test text_content property for UTF-8 files."""
        content = "Hello, 世界!"
        artifact = ArtifactFile(
            path=Path("greeting.txt"),
            content=content.encode("utf-8"),
        )

        assert artifact.text_content == content

    def test_extension_property(self) -> None:
        """Test extension property."""
        artifact = ArtifactFile(
            path=Path("script.py"),
            content=b"print('hello')",
        )

        assert artifact.extension == "py"

    def test_extension_case_insensitive(self) -> None:
        """Test extension is lowercase."""
        artifact = ArtifactFile(
            path=Path("README.MD"),
            content=b"# Hello",
        )

        assert artifact.extension == "md"

    def test_to_dict_serialization(self) -> None:
        """Test dictionary serialization."""
        metadata = ArtifactMetadata(
            workflow_id="wf-1",
            artifact_type=ArtifactType.CODE,
            is_primary=True,
        )
        artifact = ArtifactFile(
            path=Path("main.py"),
            content=b"print('hello')",
            metadata=metadata,
        )

        data = artifact.to_dict()

        assert data["path"] == "main.py"
        assert data["size_bytes"] == 14
        assert data["metadata"]["workflow_id"] == "wf-1"
        assert data["metadata"]["artifact_type"] == "code"
        assert data["metadata"]["is_primary"] is True


# ============================================================================
# Test ArtifactBundle
# ============================================================================


class TestArtifactBundle:
    """Tests for ArtifactBundle dataclass."""

    def test_create_empty_bundle(self) -> None:
        """Test creating an empty bundle."""
        bundle = ArtifactBundle(
            bundle_id="bundle-123",
            phase_id="research",
        )

        assert bundle.bundle_id == "bundle-123"
        assert bundle.phase_id == "research"
        assert bundle.file_count == 0
        assert bundle.total_size_bytes == 0
        assert bundle.primary_file is None

    def test_add_file_to_bundle(self) -> None:
        """Test adding files to a bundle."""
        bundle = ArtifactBundle(
            bundle_id="bundle-123",
            phase_id="implementation",
            workflow_id="wf-1",
        )

        artifact = bundle.add_file(
            path=Path("src/main.py"),
            content=b"print('hello')",
            artifact_type=ArtifactType.CODE,
            is_primary=True,
        )

        assert bundle.file_count == 1
        assert bundle.total_size_bytes == 14
        assert artifact.metadata.workflow_id == "wf-1"
        assert artifact.metadata.phase_id == "implementation"
        assert artifact.metadata.is_primary is True

    def test_primary_file_property(self) -> None:
        """Test primary_file returns the primary deliverable."""
        bundle = ArtifactBundle(bundle_id="b1", phase_id="p1")

        bundle.add_file(Path("secondary.txt"), b"secondary")
        bundle.add_file(Path("primary.txt"), b"primary", is_primary=True)
        bundle.add_file(Path("another.txt"), b"another")

        primary = bundle.primary_file
        assert primary is not None
        assert primary.path == Path("primary.txt")

    def test_primary_file_fallback_to_first(self) -> None:
        """Test primary_file falls back to first file if none marked."""
        bundle = ArtifactBundle(bundle_id="b1", phase_id="p1")

        bundle.add_file(Path("first.txt"), b"first")
        bundle.add_file(Path("second.txt"), b"second")

        primary = bundle.primary_file
        assert primary is not None
        assert primary.path == Path("first.txt")

    def test_to_dict_serialization(self) -> None:
        """Test bundle serialization."""
        bundle = ArtifactBundle(
            bundle_id="bundle-test",
            phase_id="research",
            workflow_id="wf-123",
            title="Research Output",
        )
        bundle.add_file(Path("summary.md"), b"# Summary\n\nFindings...")

        data = bundle.to_dict()

        assert data["bundle_id"] == "bundle-test"
        assert data["phase_id"] == "research"
        assert data["workflow_id"] == "wf-123"
        assert data["title"] == "Research Output"
        assert data["file_count"] == 1
        assert len(data["files"]) == 1

    def test_to_json_serialization(self) -> None:
        """Test JSON serialization."""
        bundle = ArtifactBundle(bundle_id="b1", phase_id="p1")
        bundle.add_file(Path("test.txt"), b"test content")

        json_str = bundle.to_json()

        assert '"bundle_id": "b1"' in json_str
        assert '"phase_id": "p1"' in json_str


# ============================================================================
# Test PhaseContext
# ============================================================================


class TestPhaseContext:
    """Tests for PhaseContext dataclass."""

    def test_create_simple_context(self) -> None:
        """Test creating a simple context without artifacts."""
        context = PhaseContext(
            task="Create a hello world program",
            phase_id="implementation",
        )

        assert context.task == "Create a hello world program"
        assert context.total_artifact_count == 0
        assert len(context.artifacts) == 0

    def test_create_context_with_artifacts(self) -> None:
        """Test creating context with artifact bundles."""
        # Create a bundle from previous phase
        research_bundle = ArtifactBundle(
            bundle_id="research-output",
            phase_id="research",
            workflow_id="wf-1",
        )
        research_bundle.add_file(
            Path("findings.md"),
            b"# Research Findings\n\nKey insights...",
            artifact_type=ArtifactType.RESEARCH_SUMMARY,
            is_primary=True,
        )

        context = PhaseContext(
            task="Use the research findings to create a plan",
            phase_id="planning",
            workflow_id="wf-1",
            artifacts=[research_bundle],
        )

        assert context.total_artifact_count == 1
        assert len(context.artifacts) == 1

    def test_to_context_files_empty(self) -> None:
        """Test generating context files with no artifacts."""
        context = PhaseContext(
            task="Simple task",
            phase_id="test",
        )

        files = context.to_context_files()

        # Should have at least the context summary
        assert len(files) >= 1
        paths = [str(p) for p, _ in files]
        assert ".context/context.json" in paths

    def test_to_context_files_with_artifacts(self) -> None:
        """Test generating context files with artifacts."""
        bundle = ArtifactBundle(bundle_id="b1", phase_id="p1")
        bundle.add_file(Path("output.txt"), b"output content")

        context = PhaseContext(
            task="Use the output",
            phase_id="p2",
            artifacts=[bundle],
        )

        files = context.to_context_files()
        paths = [str(p) for p, _ in files]

        # Should have artifact file
        assert ".context/artifacts/b1/output.txt" in paths

        # Should have bundle manifest
        assert ".context/artifacts/b1/manifest.json" in paths

        # Should have context summary
        assert ".context/context.json" in paths

    def test_to_context_files_with_additional_context(self) -> None:
        """Test generating context files with additional context files."""
        context = PhaseContext(
            task="Task with extra context",
            phase_id="test",
            context_files=[
                (Path("instructions.md"), b"# Instructions\n\nDo this..."),
                (Path("config.yaml"), b"key: value"),
            ],
        )

        files = context.to_context_files()
        paths = [str(p) for p, _ in files]

        assert ".context/instructions.md" in paths
        assert ".context/config.yaml" in paths

    def test_context_summary_content(self) -> None:
        """Test the context summary JSON content."""
        import json

        bundle = ArtifactBundle(
            bundle_id="research-output",
            phase_id="research",
            title="Research Results",
        )
        bundle.add_file(Path("summary.md"), b"# Summary")

        context = PhaseContext(
            task="Plan based on research",
            system_prompt="You are a planner",
            phase_id="planning",
            workflow_id="wf-123",
            artifacts=[bundle],
        )

        files = context.to_context_files()

        # Find context.json
        context_json = None
        for path, content in files:
            if path == Path(".context/context.json"):
                context_json = json.loads(content.decode("utf-8"))
                break

        assert context_json is not None
        assert context_json["task"] == "Plan based on research"
        assert context_json["system_prompt"] == "You are a planner"
        assert context_json["phase_id"] == "planning"
        assert context_json["workflow_id"] == "wf-123"
        assert len(context_json["artifacts"]) == 1
        assert context_json["artifacts"][0]["bundle_id"] == "research-output"
