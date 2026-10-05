"""Port for pinning a requested ref to the commit it names (evals plan, #967).

WHY THIS IS A PORT. An eval's baseline is the exact commit every run starts
from, so a ref someone typed ("main", "v1.2", a short sha) has to become a full
commit sha before anything is recorded. Reading that answer means knowing a
forge, its API and its credentials, none of which is domain knowledge. The
domain decides THAT a baseline is pinned and that an unresolved ref refuses the
command; an adapter decides how a ref is read.

This is not ``SourceCommitResolverPort``: that one reads where a default branch
is NOW, and treats unknown as recordable evidence. This one resolves a ref the
caller chose, and an unknown answer is never recorded - it refuses the edit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts._shared.repository_ref import RepositoryRef

#: What ``resolve`` promises: a full object id, 40 hex characters (SHA-1) or
#: 64 (SHA-256 repositories). Lowercase only, so one commit has exactly one
#: spelling. Defined on the port because it IS the port's contract: adapters
#: check their forge's answer against it, and the baseline refuses anything else.
FULL_COMMIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class UnresolvedReason(StrEnum):
    """Why a ref could not be pinned. Each one tells the caller what to fix."""

    #: The repository answered and has no such ref.
    NOT_FOUND = "not_found"
    #: The repository could not be read with the credentials available.
    NO_ACCESS = "no_access"
    #: The forge could not be asked: network, rate limit, outage. Retryable.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ResolvedRevision:
    """The ref named this commit at the moment it was asked."""

    commit_sha: str


@dataclass(frozen=True)
class UnresolvedRevision:
    """The ref could not be pinned, and why."""

    reason: UnresolvedReason
    detail: str = ""


RevisionResolution = ResolvedRevision | UnresolvedRevision


class RevisionResolverPort(Protocol):
    """Resolves a branch, tag or sha in a repository to a full commit sha."""

    async def resolve(self, repository: RepositoryRef, requested_ref: str, /) -> RevisionResolution:
        """The full lowercase commit sha ``requested_ref`` names in ``repository``.

        Implementations MUST NOT raise for a forge failure: every way of not
        knowing is an ``UnresolvedRevision``, so the handler can say which
        repository and ref failed and why, instead of surfacing a stack trace.
        """
        ...
