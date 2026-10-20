"""Port for asking the forge whether a path exists in a commit's tree.

docs/plans/20261015_platform-dispatched-evidence.md §A.2. Whether a pushed head
still carries `.mutations/` is a fact the evidence gate needs, and asking means
knowing a forge and its credentials, which is not domain knowledge. The adapter
lands in PR 6; until then nothing is wired and the answer is recorded unknown.
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["RemoteTreePort"]


class RemoteTreePort(Protocol):
    """Reads whether one path exists at one commit."""

    async def has_path(self, repository: str, sha: str, path: str) -> bool | None:
        """Whether ``path`` exists at ``sha`` of ``repository`` (``owner/name``).

        Implementations MUST NOT raise: a forge that cannot be asked answers
        None, which is recorded as unknown, never as absent.
        """
        ...
