"""The commits an execution records as it starts (#1457).

One entry per repository the run was given, in the order it was given them,
whether or not its commit could be read: the list says which repositories the
run had, and a None sha says honestly that one of them was not pinned.

What this records is the default-branch HEAD at START, unless the run's eval
froze a baseline for that repository: then it is the frozen commit, wherever
the branch has moved since (#967), because every run of an eval starts from
the same code. The workspace clones
later, at provisioning, so every phase of the run is checked out at the
recorded sha rather than at whatever the branch has moved to since
(`StartPins.checkout_commits`, #1458).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    SourceCommit,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration._shared.repository_baseline import (
        RepositoryBaseline,
    )
    from syn_domain.contexts.orchestration.ports.SourceCommitResolverPort import (
        SourceCommitResolverPort,
    )


async def source_commits_for(
    resolver: SourceCommitResolverPort | None,
    repos: Sequence[RepositoryRef],
    baseline: Sequence[RepositoryBaseline] = (),
) -> list[SourceCommit]:
    """The commit each of ``repos`` starts from: its frozen pin, else its head, else None."""
    pinned = {pin.repository.slug: pin.commit_sha for pin in baseline}
    return [
        SourceCommit(
            repository=repo.slug,
            sha=pinned.get(repo.slug)
            or (None if resolver is None else await resolver.head_sha(repo)),
        )
        for repo in repos
    ]
