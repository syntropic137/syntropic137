"""Value objects for artifacts bounded context."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum


class ArtifactType(StrEnum):
    """Type of artifact produced by a phase.

    Artifacts can be:
    - Content: Actual file content stored in artifact DB
    - Reference: Pointer to external resource (GitHub, URL, etc.)
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

    # Generic content
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"
    YAML = "yaml"
    EXECUTION_REPORT = "execution_report"
    OTHER = "other"

    # GitHub references (pointers, not content)
    GITHUB_COMMIT = "github_commit"  # Reference to a commit SHA
    GITHUB_PR = "github_pr"  # Reference to a pull request
    GITHUB_ISSUE = "github_issue"  # Reference to an issue
    GITHUB_FILE = "github_file"  # Reference to file at specific commit
    GITHUB_BRANCH = "github_branch"  # Reference to a branch

    # External references
    URL = "url"  # Generic URL reference
    FILE_PATH = "file_path"  # Path reference (not content)


class ContentType(StrEnum):
    """MIME type of artifact content."""

    TEXT_PLAIN = "text/plain"
    TEXT_MARKDOWN = "text/markdown"
    APPLICATION_JSON = "application/json"
    APPLICATION_YAML = "application/yaml"
    TEXT_PYTHON = "text/x-python"
    TEXT_TYPESCRIPT = "text/x-typescript"
    TEXT_JAVASCRIPT = "text/javascript"


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of content.

    Args:
        content: The content to hash.

    Returns:
        Hex-encoded SHA-256 hash (64 characters).
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PhaseOutputFile:
    """One file a phase wrote to its output directory (issue #988).

    A phase's output is a DIRECTORY, not a file. Handing the next phase a
    single ``str`` of content - which is what ``dict[str, str]`` phase outputs
    can express - is the wrong unit, and forced every file but one to be
    dropped. This pairs the content with the path it occupied so the tree can
    be reconstructed in the consuming workspace.

    ``source_path`` is workspace-relative and includes the output directory
    prefix (e.g. ``artifacts/output/raw-findings/f1.yaml``). It is optional
    because artifacts created before ArtifactCreated v5 do not carry it; a
    None here means "flat name only", never "guess a path".
    """

    source_path: str | None
    content: str
