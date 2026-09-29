"""Port for reading the commit a repository is at, as an execution starts.

WHY THIS IS A PORT (#1457). A resume runs the rest of its parent's work, and that
is only the same work if it runs against the same code. So the parent records
the commit each of its repositories was at when it started - but reading that
commit means knowing a forge, its API and its credentials, none of which is
domain knowledge. The domain decides THAT a start records its commits and what
an unknown one means; an adapter decides how one is read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts._shared.repository_ref import RepositoryRef


class SourceCommitResolverPort(Protocol):
    """Reads the commit a repository's default branch is at right now."""

    async def head_sha(self, repo: RepositoryRef) -> str | None:
        """The full sha of ``repo``'s default-branch HEAD, or None if unreadable.

        None means the commit COULD NOT BE READ - no forge access, a repository
        that is gone, a rate limit. It is recorded as unknown, never guessed.

        Implementations MUST NOT raise. Recording a commit is evidence for a
        later resume, and must never be the thing that stops this run starting.
        """
        ...
