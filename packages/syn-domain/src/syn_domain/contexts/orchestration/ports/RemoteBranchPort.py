"""Port for asking the forge where a branch is, and which PR is open from it.

WHY THIS IS A PORT (#1513). A resume continues the branch and draft PR its
parent's failing phase left, but only if they are still there: a branch that
was deleted or force-pushed since must not be reused. Asking means knowing a
forge, its API and its credentials, none of which is domain knowledge. The
domain decides what an answer MEANS (`branch_continuation.decide_continuation`);
an adapter only asks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
        RemoteBranchReading,
    )


class RemoteBranchPort(Protocol):
    """Reads one branch's head and the pull requests opened from it."""

    async def read_branch(self, repository: str, branch: str) -> RemoteBranchReading:
        """Where ``branch`` of ``repository`` (``owner/name``) is now.

        Implementations MUST NOT raise: a forge that cannot be asked answers
        ``readable=False``, which the domain reads as "do not reuse it
        unverified", never as "the branch is gone".
        """
        ...
