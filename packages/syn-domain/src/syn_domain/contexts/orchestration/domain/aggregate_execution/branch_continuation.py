"""Which branch a resumed phase continues, rather than starting over (#1513).

A v3 implement phase opens a draft PR on its first push, so a parent that fails
anywhere after that leaves a pushed branch and an open PR behind. A resume that
starts its implement phase fresh opens a SECOND branch and a second PR for the
same change. This module is the rule that stops that, in three steps, each a
pure function of recorded facts:

1. `branches_left_by` - when a run fails, which branches its failing phase
   left on origin. Read from the `observed_branches` the failure already
   records (#1200), so the fact is on the execution whether or not the phase
   completed.
2. `continuation_candidates` - when a resume is admitted, which of those the
   resumed phase should pick up: the ones its parent's failing phase left,
   when the resumed phase IS that phase.
3. `decide_continuation` - when the child starts, which candidates are still
   where the parent left them on the forge. A branch deleted, force-pushed or
   moved since, or whose PR was closed, is ABANDONED with a recorded reason and
   the phase starts fresh; nothing stale is reused, and nothing is dropped
   silently.

THE CHECKOUT RULE (ADR-058, #1458 + #1513). A phase that only READS code is
checked out at the run's pinned start commit. A phase that CONTINUES a branch
is checked out at that branch's head. `checkout_for` is the one place that
says which is which, and it says it per phase: only the resumed phase
continues, because only its own earlier attempt pushed the branch.

The models live here rather than in `value_objects` because that module is
already past the file-size limit; `value_objects` re-exports them so
`WorkflowExecutionStarted` can carry them under the vsa import rule.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

#: The only remote a workspace clones from. A branch on any other remote is
#: not one a resumed workspace could check out.
_ORIGIN = "origin"


class ContinuedBranch(BaseModel):
    """A branch a phase pushed, and the PR open from it, if any (#1513).

    As a CANDIDATE (on the resume command) it is what the parent's failing
    phase left: `head_sha` is where origin had the branch when that phase
    failed, and `pull_request` is not known yet. As a DECISION (on the child's
    start event) the forge has confirmed the branch is still at `head_sha`, and
    `pull_request` is the open PR from it, or None when there is none.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: `owner/name`, the slug `SourceCommit.repository` uses.
    repository: str
    branch: str
    head_sha: str
    pull_request: int | None = None


class AbandonedBranch(BaseModel):
    """A branch a resume could have continued and deliberately did not (#1513).

    Recorded on the child's start so the fresh start is visible, with why.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str
    branch: str
    #: Where the parent left the branch.
    head_sha: str
    reason: str


class RemoteBranchReading(BaseModel):
    """What the forge said about one branch as a resume started.

    `readable` False means nobody could ask - no forge access, a rate limit -
    and is never read as "the branch is gone".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str
    branch: str
    readable: bool
    #: Where the branch is now; None when it does not exist.
    head_sha: str | None = None
    open_pull_request: int | None = None
    #: The most recent closed or merged PR from the branch, when none is open.
    closed_pull_request: int | None = None


class PhaseCheckout(BaseModel):
    """What one phase's repositories are checked out at."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: `owner/name` -> the commit (see `SourceCommit`); for a continued
    #: branch, the head the decision confirmed.
    commits: dict[str, str] = Field(default_factory=dict)
    #: `owner/name` -> the branch to check out at its head instead of detached.
    branches: dict[str, str] = Field(default_factory=dict)


class LeftBranches(BaseModel):
    """The branches a failed run's failing phase left on origin, by that phase."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_id: str | None = None
    branches: list[ContinuedBranch] = Field(default_factory=list)


def branches_left_by(
    observed: Sequence[object] | None,
    *,
    repositories: Sequence[str],
    continued: Sequence[ContinuedBranch],
) -> list[ContinuedBranch]:
    """The branches a failing phase left on origin, as `ContinuedBranch`es.

    ``observed`` is the failure's `observed_branches` (BranchObservation or
    its replayed mapping). A branch counts when origin holds it and it is one
    the phase OWNED: either it did not exist on origin when the phase started
    (the phase created it), or the phase was itself continuing it. That
    second half is what keeps a branch the phase merely sat on - `main`
    moving under a fetch - from ever being continued.

    ``repositories`` maps an observation's directory name back to its slug; a
    name two repositories share maps to neither, rather than to a guess.
    """
    by_name: dict[str, list[str]] = {}
    for slug in repositories:
        by_name.setdefault(slug.rsplit("/", 1)[-1], []).append(slug)
    owned = {(c.repository, c.branch) for c in continued}
    left = {(c.repository, c.branch): c for c in continued}
    for raw in observed or ():
        reading = _observation(raw)
        if reading is None:
            continue
        name, branch, commit, at_start = reading
        slugs = by_name.get(name, [])
        if len(slugs) != 1:
            continue
        key = (slugs[0], branch)
        if at_start is None or key in owned:
            left[key] = ContinuedBranch(repository=slugs[0], branch=branch, head_sha=commit)
    return list(left.values())


def _observation(raw: object) -> tuple[str, str, str, str | None] | None:
    """(repo dir, branch, origin commit now, origin commit at phase start), or None.

    None for anything that is not a branch origin holds: another remote, a
    detached HEAD, a deleted ref, or a payload this reader cannot read.
    """
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        BranchObservation,
    )

    try:
        obs = raw if isinstance(raw, BranchObservation) else BranchObservation.model_validate(raw)
    except ValidationError:
        logger.warning("Unreadable observed branch on a replayed failure; ignoring it")
        return None
    if obs.remote != _ORIGIN or obs.remote_commit is None or obs.branch == "(detached HEAD)":
        return None
    return obs.repo, obs.branch, obs.remote_commit, obs.remote_commit_at_phase_start


def continuation_candidates(left: LeftBranches, resume_phase_id: str) -> list[ContinuedBranch]:
    """What a resume at ``resume_phase_id`` should try to continue.

    Only the branches the parent's FAILING phase left, and only when the
    resume resumes that same phase. A later phase that reads the branch reads
    it through its predecessor's artifact at the pinned commit; it continues
    nothing.
    """
    if left.phase_id is None or left.phase_id != resume_phase_id:
        return []
    return [c.model_copy(update={"pull_request": None}) for c in left.branches]


def decide_continuation(
    candidates: Sequence[ContinuedBranch], readings: Sequence[RemoteBranchReading]
) -> tuple[list[ContinuedBranch], list[AbandonedBranch]]:
    """Which candidates the child continues, and which it abandons and why.

    Continued only when the forge confirms the branch is exactly where the
    parent left it and no closed PR replaced an open one. Everything else is
    abandoned with the reason: the phase starts fresh, visibly.
    """
    by_key = {(r.repository, r.branch): r for r in readings}
    continued: list[ContinuedBranch] = []
    abandoned: list[AbandonedBranch] = []
    for candidate in candidates:
        reading = by_key.get((candidate.repository, candidate.branch))
        reason = _abandon_reason(candidate, reading)
        if reason is None and reading is not None:
            continued.append(
                candidate.model_copy(update={"pull_request": reading.open_pull_request})
            )
        else:
            abandoned.append(
                AbandonedBranch(
                    repository=candidate.repository,
                    branch=candidate.branch,
                    head_sha=candidate.head_sha,
                    reason=reason or "the branch was not read",
                )
            )
    return continued, abandoned


def _abandon_reason(candidate: ContinuedBranch, reading: RemoteBranchReading | None) -> str | None:
    """Why ``candidate`` may not be continued, or None when it may."""
    if reading is None or not reading.readable:
        return "the forge could not be asked where the branch is, so it was not reused unverified"
    if reading.head_sha is None:
        return "the branch no longer exists on origin (deleted)"
    if reading.head_sha != candidate.head_sha:
        return (
            f"origin has the branch at {reading.head_sha}, not {candidate.head_sha} where the "
            "parent left it (force-pushed or moved since)"
        )
    if reading.open_pull_request is None and reading.closed_pull_request is not None:
        return f"its pull request #{reading.closed_pull_request} was closed or merged"
    return None


_CONTINUED: TypeAdapter[list[ContinuedBranch]] = TypeAdapter(list[ContinuedBranch])
_ABANDONED: TypeAdapter[list[AbandonedBranch]] = TypeAdapter(list[AbandonedBranch])


def read_continued_branches(raw: object) -> list[ContinuedBranch]:
    """The continued branches on a replayed start, or empty when absent or unreadable.

    Empty fails toward a fresh start, the behaviour before #1513, and says so.
    """
    if not raw:
        return []
    try:
        return _CONTINUED.validate_python(raw)
    except ValidationError:
        logger.warning("Unreadable continued_branches on a replayed start; starting fresh")
        return []


def read_abandoned_branches(raw: object) -> list[AbandonedBranch]:
    """The abandoned branches on a replayed start, or empty when absent or unreadable."""
    if not raw:
        return []
    try:
        return _ABANDONED.validate_python(raw)
    except ValidationError:
        logger.warning("Unreadable abandoned_branches on a replayed start; ignoring them")
        return []
