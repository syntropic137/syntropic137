"""Value objects for artifacts bounded context."""

from __future__ import annotations

import hashlib
from enum import Enum


class ArtifactType(str, Enum):
    """Type of artifact produced by a phase."""

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


class ContentType(str, Enum):
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
