"""Which PR was open from each branch a failing phase left, asked as it fails (#1513).

THE PR IS A FACT ABOUT THE PARENT, so it is read while the parent fails. A
resume that only asked the forge when the child started would continue
whatever PR was open from the branch THEN: close the parent's #42, open #43
from the same branch, and the child would adopt #43 as its own. Recorded on
the failure's `observed_branches`, the parent's PR is a Lane 1 fact, and the
resume compares the forge's answer with it (`branch_continuation`).

Asked of the forge through `RemoteBranchPort` and never inside the workspace:
which PR is open from a branch is a forge question, and the port is the one
place that knows how to ask it.

NEVER RAISES, for `observe_branches`' reason: this runs on a phase that is
already dying. A forge that cannot be asked leaves the observation without a
PR, which the resume reads as "the parent recorded none" and so never trusts
a PR found later.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    repository_slugs_by_name,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import ObservedBranches

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        BranchObservation,
    )
    from syn_domain.contexts.orchestration.ports.RemoteBranchPort import RemoteBranchPort

logger = logging.getLogger(__name__)

_ORIGIN = "origin"


async def with_open_pull_requests(
    observed: ObservedBranches | None,
    forge: RemoteBranchPort,
    repositories: Sequence[str],
) -> ObservedBranches | None:
    """``observed`` with the PR the forge has open from each origin branch in it.

    ``repositories`` are the run's `owner/name` slugs; an observation's
    directory name that two of them share maps to neither and is left as is.
    """
    if observed is None:
        return None
    slugs = repository_slugs_by_name(repositories)
    branches = [await _with_pull_request(b, forge, slugs) for b in observed.branches]
    return ObservedBranches(branches=tuple(branches), unreadable=observed.unreadable)


async def _with_pull_request(
    branch: BranchObservation, forge: RemoteBranchPort, slugs: dict[str, str]
) -> BranchObservation:
    slug = slugs.get(branch.repo)
    if branch.remote != _ORIGIN or branch.remote_commit is None or slug is None:
        return branch
    reading = await forge.read_branch(slug, branch.branch)
    if not reading.readable:
        logger.warning("Could not ask which PR is open from %s in %s", branch.branch, slug)
        return branch
    return branch.model_copy(update={"pull_request": reading.open_pull_request})
