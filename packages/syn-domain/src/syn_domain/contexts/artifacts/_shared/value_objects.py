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
    """MIME type of artifact content.

    The text members say how to READ a ``str``; the binary members (#990) say
    the content is bytes and has no ``str`` form at all. Before #990 there were
    no binary members, so every collected file was decoded as UTF-8 to fit -
    and a PNG came back as U+FFFD followed by "PNG".
    """

    TEXT_PLAIN = "text/plain"
    TEXT_MARKDOWN = "text/markdown"
    APPLICATION_JSON = "application/json"
    APPLICATION_YAML = "application/yaml"
    TEXT_PYTHON = "text/x-python"
    TEXT_TYPESCRIPT = "text/x-typescript"
    TEXT_JAVASCRIPT = "text/javascript"

    # Binary (#990). Content lives in object storage only (ADR-012): the
    # event records the fact, its hash and its size, never the bytes.
    IMAGE_PNG = "image/png"
    IMAGE_JPEG = "image/jpeg"
    IMAGE_GIF = "image/gif"
    IMAGE_WEBP = "image/webp"
    APPLICATION_PDF = "application/pdf"
    APPLICATION_OCTET_STREAM = "application/octet-stream"

    @property
    def is_binary(self) -> bool:
        """Whether content of this type is bytes with no text form."""
        return self in _BINARY_CONTENT_TYPES

    @classmethod
    def of(cls, data: bytes, source_path: str | None = None) -> ContentType:
        """What ``data`` is, judged by its bytes and, failing that, its name.

        Text is anything that is valid UTF-8 without a NUL byte, and keeps the
        type every collected file had before #990 - so a text artifact is
        stored exactly as it always was. Only content that CANNOT be text is
        binary: its signature names it where it has one, then the file
        extension, then ``application/octet-stream``. Never the other way
        round: an extension alone cannot make valid text binary, and a ``.md``
        holding PNG bytes is still a PNG.
        """
        if b"\x00" not in data:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                return cls.TEXT_MARKDOWN
        for signature, content_type in _BINARY_SIGNATURES:
            if data.startswith(signature):
                if content_type is cls.IMAGE_WEBP and data[8:12] != b"WEBP":
                    continue
                return content_type
        if source_path is not None:
            extension = source_path.rsplit(".", 1)[-1].lower() if "." in source_path else ""
            by_extension = _BINARY_EXTENSIONS.get(extension)
            if by_extension is not None:
                return by_extension
        return cls.APPLICATION_OCTET_STREAM


_BINARY_CONTENT_TYPES: frozenset[ContentType] = frozenset(
    {
        ContentType.IMAGE_PNG,
        ContentType.IMAGE_JPEG,
        ContentType.IMAGE_GIF,
        ContentType.IMAGE_WEBP,
        ContentType.APPLICATION_PDF,
        ContentType.APPLICATION_OCTET_STREAM,
    }
)

_BINARY_SIGNATURES: tuple[tuple[bytes, ContentType], ...] = (
    (b"\x89PNG\r\n\x1a\n", ContentType.IMAGE_PNG),
    (b"\xff\xd8\xff", ContentType.IMAGE_JPEG),
    (b"GIF87a", ContentType.IMAGE_GIF),
    (b"GIF89a", ContentType.IMAGE_GIF),
    (b"RIFF", ContentType.IMAGE_WEBP),  # confirmed by "WEBP" at offset 8
    (b"%PDF-", ContentType.APPLICATION_PDF),
)

_BINARY_EXTENSIONS: dict[str, ContentType] = {
    "png": ContentType.IMAGE_PNG,
    "jpg": ContentType.IMAGE_JPEG,
    "jpeg": ContentType.IMAGE_JPEG,
    "gif": ContentType.IMAGE_GIF,
    "webp": ContentType.IMAGE_WEBP,
    "pdf": ContentType.APPLICATION_PDF,
}


def compute_content_hash(content: str | bytes) -> str:
    """SHA-256 of the content's BYTES, hex-encoded (64 characters).

    Text is hashed as its UTF-8 encoding, which is exactly what it was before
    #990, so every existing ``content_hash`` is unchanged and still verifies.
    Binary is hashed as-is: the hash is of the file the agent wrote, not of
    any decoding of it (#990 hashed the U+FFFD-mangled text, which verified
    nothing).
    """
    data = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(data).hexdigest()


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
    #: ``str`` for text, ``bytes`` for a binary file (#990). The handoff writes
    #: either to the next workspace unchanged; only text can be a phase's
    #: primary deliverable, because prompt substitution needs a string.
    content: str | bytes


def primary_text(files: list[PhaseOutputFile]) -> str | None:
    """The text that stands for a phase's output, or None if it has none.

    The first file with text content, because every source puts the primary
    deliverable at the head: the projection sorts by ``_injection_rank``, which
    ranks the explicitly-flagged primary first (#997), and the live path
    collects in the order it flagged. Choosing by any other rule would recreate
    the disagreement #1149 removed, one layer down - which is why the flat
    alias and a resume's inherited primary both ask this one function.

    Empty content is not a deliverable - `CreateArtifactCommand` rejects it and
    every other reader skips it, so a legacy or corrupt row cannot become the
    primary. Nor is a binary file (#990): the primary is read as the phase's
    text, and a screenshot reaches the next phase through the tree at its own
    path instead.
    """
    return next((f.content for f in files if isinstance(f.content, str) and f.content), None)


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
