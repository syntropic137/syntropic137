"""Port for the platform's one branch write: removing `.mutations/` (plan §A.5, PR 5b).

A compare-and-swap with no pre-event: the result identifies itself, so a
removal whose event was lost is ADOPTED on retry rather than written twice.
The GitHub adapter lands in PR 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["Adopted", "HeadMoved", "RemoteBranchWriterPort", "RemovalResult", "Removed"]


@dataclass(frozen=True)
class Removed:
    """This call wrote the commit S -> S'."""

    after_sha: str
    author: str


@dataclass(frozen=True)
class Adopted:
    """The branch is already at a commit that removed exactly these paths from S."""

    after_sha: str
    author: str


@dataclass(frozen=True)
class HeadMoved:
    """The branch is at neither S nor our S'; nothing was written."""

    head_sha: str | None


RemovalResult = Removed | Adopted | HeadMoved


class RemoteBranchWriterPort(Protocol):
    async def remove_paths(
        self, repository: str, branch: str, before_sha: str, paths: tuple[str, ...]
    ) -> RemovalResult:
        """Remove ``paths`` from ``branch`` iff it is at ``before_sha``. MUST NOT raise."""
        ...
