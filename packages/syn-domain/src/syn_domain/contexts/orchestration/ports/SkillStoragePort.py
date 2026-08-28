"""Storage port for skill trees (issue #772).

A skill is a directory tree containing `SKILL.md` with YAML frontmatter
(name, description), per the vercel-labs/skills convention. Storage is
content-addressed: trees are keyed by the sha256 of their normalized
contents so the same skill at the same version always lands at the same
prefix. Trees land in workspaces at
`<workspace>/.syn-skills/<skill_name>/<rel_path>`.

Implementations:
    - MinioSkillStorage: production / development (S3-compatible)
    - InMemorySkillStorage: unit tests only
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SkillFile:
    """One file inside a skill tree.

    Paths are workspace-relative (no leading slash), POSIX-style ("/"
    separators), as they will appear inside the workspace at
    `<workspace>/.syn-skills/<skill_name>/<rel_path>`.
    """

    rel_path: str
    content: bytes


@dataclass(frozen=True)
class StoredSkillTree:
    """Result of uploading a skill tree to storage."""

    storage_prefix: str
    """The MinIO prefix under which all files for this tree live."""

    sha256: str
    """SHA-256 of the normalized tree (sorted by rel_path then content)."""

    file_count: int
    total_size_bytes: int

    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillStorageStats:
    """How much space registered skill trees occupy.

    Skill storage grows monotonically: registration is content-addressed and
    nothing removes old trees. Eviction is deliberately not implemented, so
    this exists to keep that a measured decision rather than an assumption.
    """

    object_count: int = 0
    total_bytes: int = 0
    skill_count: int = 0
    """Distinct sha256-keyed trees, not files."""

    truncated: bool = False
    """True if the backend returned a partial listing, so the counts are lower
    bounds. Reported rather than hidden: a silently capped total reads as a
    complete one."""


@runtime_checkable
class SkillStoragePort(Protocol):
    """Stores and fetches skill trees in the platform's object storage.

    Trees are immutable; once a sha256-keyed tree is uploaded, it is never
    modified. Re-uploading the same tree is a safe no-op.
    """

    async def upload_tree(
        self,
        sha256: str,
        files: list[SkillFile],
    ) -> StoredSkillTree:
        """Upload every file in the tree under a sha256-keyed prefix.

        Args:
            sha256: The pre-computed sha256 of the normalized tree.
            files: All files in the skill tree.

        Returns:
            StoredSkillTree with the prefix the caller can later
            pass to fetch_tree().
        """
        ...

    async def fetch_tree(self, sha256: str) -> list[SkillFile]:
        """Read every file in the tree from storage.

        Args:
            sha256: The sha256 of the tree to fetch.

        Returns:
            All files. Order is not guaranteed; callers depending on order
            must sort by rel_path.
        """
        ...

    async def exists(self, sha256: str) -> bool:
        """Check if a tree with this sha256 has been uploaded."""
        ...

    def prefix_for(self, sha256: str) -> str:
        """Return the storage prefix for a sha256 without uploading.

        WHY (issue #772): cache-hit path needs the same prefix as a fresh
        upload would have produced. Exposing it lets the registration handler
        skip a redundant ``upload_tree`` call when ``exists(sha256)`` is True.
        """
        ...

    async def stats(self) -> SkillStorageStats:
        """Report object count, total bytes, and distinct tree count."""
        ...

    async def ensure_ready(self) -> None:
        """Ensure underlying storage backend is ready (bucket exists, etc.)."""
        ...
