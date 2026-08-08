"""In-memory skill tree storage adapter - TESTS ONLY (issue #772)."""

from __future__ import annotations

from syn_adapters.in_memory import InMemoryAdapter
from syn_domain.contexts.orchestration.ports.SkillStoragePort import (
    SkillFile,
    StoredSkillTree,
)


class SkillStorageError(Exception):
    """Raised when a skill storage operation fails."""


class InMemorySkillStorage(InMemoryAdapter):
    """In-memory skill storage for unit tests.

    Inherits environment guard from InMemoryAdapter. Stores trees in a
    dict (lost on process exit).
    """

    def __init__(self) -> None:
        super().__init__()
        self._trees: dict[str, list[SkillFile]] = {}

    async def upload_tree(
        self,
        sha256: str,
        files: list[SkillFile],
    ) -> StoredSkillTree:
        if not files:
            msg = "Cannot upload empty skill tree"
            raise SkillStorageError(msg)
        # Defensive copy so callers can't mutate the stored tree.
        self._trees[sha256] = [SkillFile(rel_path=f.rel_path, content=f.content) for f in files]
        total_bytes = sum(len(f.content) for f in files)
        return StoredSkillTree(
            storage_prefix=f"memory://skills/sha256-{sha256}",
            sha256=sha256,
            file_count=len(files),
            total_size_bytes=total_bytes,
        )

    async def fetch_tree(self, sha256: str) -> list[SkillFile]:
        if sha256 not in self._trees:
            msg = f"No skill tree found for sha256={sha256}"
            raise SkillStorageError(msg)
        return [SkillFile(rel_path=f.rel_path, content=f.content) for f in self._trees[sha256]]

    async def exists(self, sha256: str) -> bool:
        return sha256 in self._trees

    def prefix_for(self, sha256: str) -> str:
        """Return the in-memory pseudo-prefix matching ``upload_tree`` (issue #772)."""
        return f"memory://skills/sha256-{sha256}"

    async def ensure_ready(self) -> None:
        return None

    def clear(self) -> None:
        """Clear all stored trees (for test cleanup)."""
        self._trees.clear()

    @property
    def count(self) -> int:
        """Number of stored trees (for test assertions)."""
        return len(self._trees)
