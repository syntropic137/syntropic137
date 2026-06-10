"""Storage port for claude plugin trees (issue #726).

A claude plugin is a directory tree (containing `.claude-plugin/plugin.json`
and typically `skills/`, `hooks/`, `commands/`). Storage is content-addressed:
trees are keyed by the sha256 of their normalized contents so the same plugin
at the same version always lands at the same prefix.

Implementations:
    - MinioClaudePluginStorage: production / development (S3-compatible)
    - InMemoryClaudePluginStorage: unit tests only
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ClaudePluginFile:
    """One file inside a claude plugin tree.

    Paths are workspace-relative (no leading slash), POSIX-style ("/"
    separators), as they will appear inside the workspace at
    `<workspace>/.syn-plugins/<plugin>/<rel_path>`.
    """

    rel_path: str
    content: bytes


@dataclass(frozen=True)
class StoredClaudePluginTree:
    """Result of uploading a claude plugin tree to storage."""

    storage_prefix: str
    """The MinIO prefix under which all files for this tree live."""

    sha256: str
    """SHA-256 of the normalized tree (sorted by rel_path then content)."""

    file_count: int
    total_size_bytes: int

    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class ClaudePluginStoragePort(Protocol):
    """Stores and fetches claude plugin trees in the platform's object storage.

    Trees are immutable; once a sha256-keyed tree is uploaded, it is never
    modified. Re-uploading the same tree is a safe no-op.
    """

    async def upload_tree(
        self,
        sha256: str,
        files: list[ClaudePluginFile],
    ) -> StoredClaudePluginTree:
        """Upload every file in the tree under a sha256-keyed prefix.

        Args:
            sha256: The pre-computed sha256 of the normalized tree.
            files: All files in the plugin tree.

        Returns:
            StoredClaudePluginTree with the prefix the caller can later
            pass to fetch_tree().
        """
        ...

    async def fetch_tree(self, sha256: str) -> list[ClaudePluginFile]:
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

        WHY (issue #726): cache-hit path needs the same prefix as a fresh
        upload would have produced. Exposing it lets the registration handler
        skip a redundant ``upload_tree`` call when ``exists(sha256)`` is True.
        """
        ...

    async def ensure_ready(self) -> None:
        """Ensure underlying storage backend is ready (bucket exists, etc.)."""
        ...
