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


@dataclass(frozen=True)
class AgentIdentity:
    """Who produced a phase's output: the harness that ran, and the model it
    announced while running (issue #1284).

    A cross-model review's entire value is that a DIFFERENT model checked the
    work, and nothing in the artifact record used to say which one did. Every
    review produced before this existed opened by stating it could not
    determine the models that ran its own phases.

    THE TWO FIELDS ARE NOT THE SAME KIND OF FACT, which is the whole reason
    this is one type rather than two loose strings:

    * ``provider`` is what the platform LAUNCHED. We chose the binary and ran
      it, so config and reality cannot diverge - there is no path by which a
      claude launch becomes a codex process.
    * ``model`` is what the running harness ANNOUNCED on its own stream, and it
      is deliberately NOT the model the phase requested. Those differ in
      practice: a codex phase ignores a forwarded claude model, and a harness
      may serve a different model than the one asked for. Writing the requested
      value here would make the field worse than absent, because a reader would
      take it as evidence of what ran.

    ``None`` on either therefore means "not reported", never "same as
    requested" and never "unknown, so assume the default". ``model`` is None
    for every codex phase today: the codex stream carries no model (the same
    reason its cost goes unpriced rather than guessed - issue #788). The
    provider alone still settles whether two phases ran on different harnesses,
    which is the cross-model question; the model adds precision where the
    harness reports it.
    """

    provider: str | None = None
    model: str | None = None


#: What an artifact created outside a phase run carries: no harness ran it, so
#: there is nothing to report. Distinct from a phase whose harness announced
#: nothing only in how it got here, which is why both read as None.
UNREPORTED_AGENT: AgentIdentity = AgentIdentity()
