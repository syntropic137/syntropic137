"""Value objects for artifacts bounded context."""

from __future__ import annotations

import hashlib
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
