"""Artifact bundle model for phase-to-phase context flow.

This module provides types for collecting agent outputs and passing
them as context to subsequent workflow phases.

Example:
    # Collect artifacts from a completed phase
    bundle = ArtifactBundle.from_workspace(workspace, phase_id="research")

    # Inject as context for next phase
    context = PhaseContext(
        artifacts=[bundle],
        instructions="Use the research findings to create a plan",
    )
    await workspace.inject_context(context.to_files())
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any


class ArtifactType(str, Enum):
    """Type of artifact produced by a phase.

    Mirrors the domain ArtifactType for consistency.
    """

    # Research artifacts
    RESEARCH_SUMMARY = "research_summary"
    ANALYSIS_REPORT = "analysis_report"

    # Planning artifacts
    PLAN = "plan"
    REQUIREMENTS = "requirements"
    DESIGN_DOC = "design_doc"

    # Implementation artifacts
    CODE = "code"
    CONFIGURATION = "configuration"
    SCRIPT = "script"

    # Documentation artifacts
    DOCUMENTATION = "documentation"
    README = "readme"
    API_SPEC = "api_spec"

    # Test artifacts
    TEST_RESULTS = "test_results"
    COVERAGE_REPORT = "coverage_report"

    # Generic
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"
    YAML = "yaml"
    EXECUTION_REPORT = "execution_report"
    OTHER = "other"


@dataclass(frozen=True)
class ArtifactMetadata:
    """Metadata for an artifact file.

    Tracks provenance and context for each artifact.
    """

    # Source identification
    workflow_id: str | None = None
    phase_id: str | None = None
    session_id: str | None = None

    # Artifact classification
    artifact_type: ArtifactType = ArtifactType.OTHER
    title: str | None = None
    description: str | None = None

    # Flags
    is_primary: bool = False  # Is this the main deliverable?

    # Lineage
    derived_from: tuple[str, ...] = ()  # Parent artifact IDs

    # Custom metadata
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactFile:
    """A single file in an artifact bundle.

    Represents one output file from an agent execution,
    with content and metadata.
    """

    # File identification
    path: Path  # Relative path within output directory
    content: bytes  # Raw file content

    # Computed properties
    content_hash: str = field(default="")  # SHA-256 hash
    size_bytes: int = field(default=0)

    # Metadata
    metadata: ArtifactMetadata = field(default_factory=ArtifactMetadata)

    # Timestamp
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Compute hash and size if not provided."""
        if not self.content_hash:
            computed_hash = hashlib.sha256(self.content).hexdigest()
            object.__setattr__(self, "content_hash", computed_hash)
        if not self.size_bytes:
            object.__setattr__(self, "size_bytes", len(self.content))

    @property
    def text_content(self) -> str:
        """Get content as UTF-8 text (for text files)."""
        return self.content.decode("utf-8")

    @property
    def extension(self) -> str:
        """Get file extension (lowercase, without dot)."""
        return self.path.suffix.lstrip(".").lower()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "path": str(self.path),
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "metadata": {
                "workflow_id": self.metadata.workflow_id,
                "phase_id": self.metadata.phase_id,
                "session_id": self.metadata.session_id,
                "artifact_type": self.metadata.artifact_type.value,
                "title": self.metadata.title,
                "description": self.metadata.description,
                "is_primary": self.metadata.is_primary,
                "derived_from": list(self.metadata.derived_from),
                "extra": self.metadata.extra,
            },
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ArtifactBundle:
    """A collection of artifact files from a phase execution.

    Bundles group related outputs for passing between phases.
    A phase can produce multiple bundles (e.g., code + docs).
    """

    # Bundle identification
    bundle_id: str
    phase_id: str
    session_id: str | None = None
    workflow_id: str | None = None

    # Files in this bundle
    files: list[ArtifactFile] = field(default_factory=list)

    # Bundle metadata
    title: str | None = None
    description: str | None = None
    is_primary: bool = True  # Is this the main output bundle?

    # Timestamp
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def total_size_bytes(self) -> int:
        """Total size of all files in bytes."""
        return sum(f.size_bytes for f in self.files)

    @property
    def file_count(self) -> int:
        """Number of files in bundle."""
        return len(self.files)

    @property
    def primary_file(self) -> ArtifactFile | None:
        """Get the primary deliverable file, if any."""
        for f in self.files:
            if f.metadata.is_primary:
                return f
        return self.files[0] if self.files else None

    def add_file(
        self,
        path: Path,
        content: bytes,
        *,
        artifact_type: ArtifactType = ArtifactType.OTHER,
        title: str | None = None,
        is_primary: bool = False,
        **extra_metadata: Any,
    ) -> ArtifactFile:
        """Add a file to the bundle.

        Args:
            path: Relative path for the file
            content: Raw file content
            artifact_type: Type of artifact
            title: Optional title
            is_primary: Is this the primary deliverable?
            **extra_metadata: Additional metadata fields

        Returns:
            The created ArtifactFile
        """
        metadata = ArtifactMetadata(
            workflow_id=self.workflow_id,
            phase_id=self.phase_id,
            session_id=self.session_id,
            artifact_type=artifact_type,
            title=title,
            is_primary=is_primary,
            extra=extra_metadata,
        )

        artifact = ArtifactFile(
            path=path,
            content=content,
            metadata=metadata,
        )

        self.files.append(artifact)
        return artifact

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "bundle_id": self.bundle_id,
            "phase_id": self.phase_id,
            "session_id": self.session_id,
            "workflow_id": self.workflow_id,
            "title": self.title,
            "description": self.description,
            "is_primary": self.is_primary,
            "files": [f.to_dict() for f in self.files],
            "total_size_bytes": self.total_size_bytes,
            "file_count": self.file_count,
            "created_at": self.created_at.isoformat(),
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class PhaseContext:
    """Context to inject into a workspace for a phase execution.

    Combines artifacts from previous phases with instructions
    for the current phase.
    """

    # Instructions for this phase
    task: str  # The main task/prompt
    system_prompt: str | None = None

    # Context from previous phases
    artifacts: list[ArtifactBundle] = field(default_factory=list)

    # Additional context files (not from artifacts)
    context_files: list[tuple[Path, bytes]] = field(default_factory=list)

    # Phase identification
    phase_id: str | None = None
    workflow_id: str | None = None

    @property
    def total_artifact_count(self) -> int:
        """Total files across all artifact bundles."""
        return sum(bundle.file_count for bundle in self.artifacts)

    def to_context_files(self) -> list[tuple[Path, bytes]]:
        """Convert all artifacts and context to injectable files.

        Returns list of (relative_path, content) tuples ready for
        workspace injection.
        """
        files: list[tuple[Path, bytes]] = []

        # Add artifact files under .context/artifacts/{bundle_id}/
        for bundle in self.artifacts:
            bundle_dir = Path(".context") / "artifacts" / bundle.bundle_id

            for artifact_file in bundle.files:
                context_path = bundle_dir / artifact_file.path
                files.append((context_path, artifact_file.content))

            # Add bundle manifest
            manifest_path = bundle_dir / "manifest.json"
            manifest_content = bundle.to_json().encode("utf-8")
            files.append((manifest_path, manifest_content))

        # Add any additional context files
        for path, content in self.context_files:
            context_path = Path(".context") / path
            files.append((context_path, content))

        # Add phase context summary
        summary = self._create_context_summary()
        summary_path = Path(".context") / "context.json"
        files.append((summary_path, summary.encode("utf-8")))

        return files

    def _create_context_summary(self) -> str:
        """Create a JSON summary of the phase context."""
        summary = {
            "phase_id": self.phase_id,
            "workflow_id": self.workflow_id,
            "task": self.task,
            "system_prompt": self.system_prompt,
            "artifacts": [
                {
                    "bundle_id": b.bundle_id,
                    "phase_id": b.phase_id,
                    "title": b.title,
                    "file_count": b.file_count,
                    "files": [str(f.path) for f in b.files],
                }
                for b in self.artifacts
            ],
            "context_files": [str(p) for p, _ in self.context_files],
        }
        return json.dumps(summary, indent=2)
