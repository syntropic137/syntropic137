"""In-memory claude plugin tree storage adapter - TESTS ONLY (issue #726)."""

from __future__ import annotations

from syn_adapters.in_memory import InMemoryAdapter
from syn_domain.contexts.orchestration.ports.ClaudePluginStoragePort import (
    ClaudePluginFile,
    StoredClaudePluginTree,
)


class ClaudePluginStorageError(Exception):
    """Raised when a claude plugin storage operation fails."""


class InMemoryClaudePluginStorage(InMemoryAdapter):
    """In-memory claude plugin storage for unit tests.

    Inherits environment guard from InMemoryAdapter. Stores trees in a
    dict (lost on process exit).
    """

    def __init__(self) -> None:
        super().__init__()
        self._trees: dict[str, list[ClaudePluginFile]] = {}

    async def upload_tree(
        self,
        sha256: str,
        files: list[ClaudePluginFile],
    ) -> StoredClaudePluginTree:
        if not files:
            msg = "Cannot upload empty claude plugin tree"
            raise ClaudePluginStorageError(msg)
        # Defensive copy so callers can't mutate the stored tree.
        self._trees[sha256] = [
            ClaudePluginFile(rel_path=f.rel_path, content=f.content) for f in files
        ]
        total_bytes = sum(len(f.content) for f in files)
        return StoredClaudePluginTree(
            storage_prefix=f"memory://claude-plugins/sha256-{sha256}",
            sha256=sha256,
            file_count=len(files),
            total_size_bytes=total_bytes,
        )

    async def fetch_tree(self, sha256: str) -> list[ClaudePluginFile]:
        if sha256 not in self._trees:
            msg = f"No claude plugin tree found for sha256={sha256}"
            raise ClaudePluginStorageError(msg)
        return [
            ClaudePluginFile(rel_path=f.rel_path, content=f.content) for f in self._trees[sha256]
        ]

    async def exists(self, sha256: str) -> bool:
        return sha256 in self._trees

    def prefix_for(self, sha256: str) -> str:
        """Return the in-memory pseudo-prefix matching ``upload_tree`` (issue #726)."""
        return f"memory://claude-plugins/sha256-{sha256}"

    async def ensure_ready(self) -> None:
        return None

    def clear(self) -> None:
        """Clear all stored trees (for test cleanup)."""
        self._trees.clear()

    @property
    def count(self) -> int:
        """Number of stored trees (for test assertions)."""
        return len(self._trees)
