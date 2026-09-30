"""The commits an execution records as it starts (#1457).

One entry per repository the run was given, in the order it was given them,
whether or not its commit could be read: the list says which repositories the
run had, and a None sha says honestly that one of them was not pinned.

What this records is the default-branch HEAD at START. The workspace clones
later, at provisioning, so a push landing in between is not what the recorded
sha names; #1458 closes that by cloning at the recorded sha.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    SourceCommit,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration.ports.SourceCommitResolverPort import (
        SourceCommitResolverPort,
    )


async def source_commits_for(
    resolver: SourceCommitResolverPort | None,
    repos: Sequence[RepositoryRef],
) -> list[SourceCommit]:
    """The commit each of ``repos`` is at, None where it cannot be read."""
    return [
        SourceCommit(
            repository=repo.slug,
            sha=None if resolver is None else await resolver.head_sha(repo),
        )
        for repo in repos
    ]
