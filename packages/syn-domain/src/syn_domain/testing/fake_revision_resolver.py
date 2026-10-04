"""A ``RevisionResolverPort`` answered from a table the test writes (#967).

The real resolver is a later evals run; until then every consumer of the port
is tested against this one, and so is the contract it has to keep.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.ports.RevisionResolverPort import (
    ResolvedRevision,
    RevisionResolution,
    UnresolvedReason,
    UnresolvedRevision,
)

if TYPE_CHECKING:
    from syn_domain.contexts._shared.repository_ref import RepositoryRef


@dataclass
class FakeRevisionResolver:
    """Resolves ``(owner/name, ref)`` from ``shas``; anything else is NOT_FOUND."""

    #: ``(repository slug, requested ref) -> full commit sha``.
    shas: dict[tuple[str, str], str] = field(default_factory=dict)
    #: Repositories that answer UNAVAILABLE whatever ref is asked for.
    unavailable: set[str] = field(default_factory=set)
    #: Every ``(slug, ref)`` asked for, in order.
    asked: list[tuple[str, str]] = field(default_factory=list)

    async def resolve(self, repository: RepositoryRef, requested_ref: str, /) -> RevisionResolution:
        self.asked.append((repository.slug, requested_ref))
        if repository.slug in self.unavailable:
            return UnresolvedRevision(UnresolvedReason.UNAVAILABLE, "forge unreachable")
        sha = self.shas.get((repository.slug, requested_ref))
        if sha is None:
            return UnresolvedRevision(UnresolvedReason.NOT_FOUND)
        return ResolvedRevision(sha)
