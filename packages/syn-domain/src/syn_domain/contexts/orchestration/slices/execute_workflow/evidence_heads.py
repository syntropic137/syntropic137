"""Read the forge's heads for the branches an evidence gate may ask about.

docs/plans/20261015_platform-dispatched-evidence.md §A.2. Host-side, during
collection and BEFORE `aggregate.artifacts_collected`, so the observation is a
fact on `ArtifactsCollectedForPhase` and the aggregate does no I/O. Recorded
only: nothing decides on it yet (PR 5b).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    repository_slugs_by_name,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_record import (
    ObservedHead,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.ports.RemoteBranchPort import RemoteBranchPort
    from syn_domain.contexts.orchestration.ports.RemoteTreePort import RemoteTreePort

logger = logging.getLogger(__name__)

#: Where `scripts/mutation_evidence.py` reads its patches from.
MUTATIONS_PATH: Final = ".mutations"


class EvidenceHeadObserver:
    """Asks the forge where each branch of an execution is, as one phase finishes."""

    def __init__(self, branches: RemoteBranchPort, tree: RemoteTreePort | None = None) -> None:
        self._branches = branches
        #: Optional until PR 6 wires an adapter; without one patch presence is
        #: recorded unknown, never absent.
        self._tree = tree

    async def observe(
        self, aggregate: WorkflowExecutionAggregate, phase_id: str
    ) -> tuple[ObservedHead, ...]:
        """One head per branch this execution pushed, inherited or ``phase_id`` declared."""
        return tuple(
            [
                await self._read(repository, branch)
                for repository, branch in _branches(aggregate, phase_id)
            ]
        )

    async def _read(self, repository: str, branch: str) -> ObservedHead:
        reading = await self._branches.read_branch(repository, branch)
        if not reading.readable or reading.head_sha is None:
            return ObservedHead(
                repository=repository,
                branch=branch,
                readable=reading.readable,
                head_sha=None,
            )
        present = None
        if self._tree is not None:
            present = await self._tree.has_path(repository, reading.head_sha, MUTATIONS_PATH)
        return ObservedHead(
            repository=repository,
            branch=branch,
            readable=True,
            head_sha=reading.head_sha,
            mutation_patches_present=present,
            open_pr_number=reading.open_pull_request,
        )


def _branches(aggregate: WorkflowExecutionAggregate, phase_id: str) -> list[tuple[str, str]]:
    """`(owner/name, branch)` to read, each once, in the order first named."""
    pins = aggregate.start_pins
    slugs = repository_slugs_by_name([c.repository for c in pins.source_commits])
    seen: dict[tuple[str, str], None] = {}
    for pushed in aggregate.pushed_commits:
        slug = slugs.get(pushed.repository)
        if slug is None:
            # A clone directory two repositories share, or none: no slug to ask.
            logger.warning(
                "Cannot observe %s: clone %s maps to no single repository",
                pushed.branch,
                pushed.repository,
            )
            continue
        seen[(slug, pushed.branch)] = None
    # A resume does not replay its parent's pushes; what it inherited is here.
    for continued in pins.continued_branches:
        seen[(continued.repository, continued.branch)] = None
    for declared in aggregate.declared_evidence_for(phase_id):
        if declared.request is not None:
            seen[(declared.request.repository, declared.request.branch)] = None
    return list(seen)
